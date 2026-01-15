#!/usr/bin/env python3
"""YouTube 번역 에이전트 웹 서버"""

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
import anthropic

load_dotenv()

app = FastAPI(title="YouTube 번역 에이전트")

OUTPUT_DIR = Path(__file__).parent / "output"
STATIC_DIR = Path(__file__).parent / "static"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# 작업 상태 저장
jobs: dict = {}


class TranslateRequest(BaseModel):
    url: str


class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, processing, completed, failed
    video_id: Optional[str] = None
    error: Optional[str] = None
    result: Optional[dict] = None


def extract_video_id(url: str) -> str:
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"유효한 YouTube URL이 아닙니다: {url}")


def extract_transcript(video_id: str) -> str:
    api = YouTubeTranscriptApi()
    try:
        transcript = api.fetch(video_id, languages=['en', 'en-US', 'ko'])
    except Exception:
        transcript = api.fetch(video_id)
    return " ".join([item.text for item in transcript])


def translate(client: anthropic.Anthropic, text: str) -> str:
    system_prompt = """당신은 전문 번역가입니다. 비즈니스/자기계발 콘텐츠를 한국 독자가 자연스럽게 읽을 수 있도록 번역합니다.

## 번역 원칙
1. **의역 우선**: 직역보다 의미 전달을 우선합니다
2. **비즈니스 용어**: 한국에서 통용되는 표현으로 변환
3. **구어체 유지**: 영상의 대화체 느낌을 살립니다
4. **고유명사**: 원문 유지 (Alex Hormozi, Acquisition.com 등)

## 출력 형식
- 타임스탬프 없이 자연스럽게 이어지는 텍스트로 번역
- 문단 구분은 주제가 바뀔 때만"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": f"다음 영어 스크립트를 한글로 번역해주세요:\n\n{text}"}]
    )
    return response.content[0].text


def summarize(client: anthropic.Anthropic, korean_text: str) -> dict:
    system_prompt = """당신은 콘텐츠 에디터입니다. 비즈니스 콘텐츠를 분석하고 구조화합니다.

## 출력 형식
반드시 아래 JSON 구조로만 응답하세요. 다른 텍스트 없이 JSON만 출력합니다.
{
  "one_liner": "한 줄 요약 (30자 이내)",
  "tags": ["태그1", "태그2", "태그3"],
  "difficulty": "입문|중급|고급",
  "keywords": ["키워드1", "키워드2"],
  "key_points": [
    {"title": "핵심 포인트 제목", "description": "설명", "example": "예시"}
  ],
  "quotes": [
    {"original": "원문", "korean": "한글 번역"}
  ],
  "action_items": ["액션1", "액션2"],
  "related_topics": ["관련 주제1", "관련 주제2"]
}"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": f"다음 콘텐츠를 분석하고 JSON으로 구조화해주세요:\n\n{korean_text}"}]
    )
    result_text = response.content[0].text
    json_text = re.sub(r'^```json\s*|\s*```$', '', result_text.strip())
    return json.loads(json_text)


def generate_html(video_id: str, korean: str, summary: dict) -> str:
    """결과를 HTML로 변환"""
    tags_html = "".join([f'<span class="tag">{tag}</span>' for tag in summary.get('tags', [])])

    key_points_html = ""
    for point in summary.get('key_points', []):
        example = f'<p class="example">{point.get("example", "")}</p>' if point.get("example") else ""
        key_points_html += f'''
        <div class="key-point">
            <h4>{point.get("title", "")}</h4>
            <p>{point.get("description", "")}</p>
            {example}
        </div>'''

    quotes_html = ""
    for quote in summary.get('quotes', []):
        quotes_html += f'''
        <blockquote class="quote">
            <p class="original">"{quote.get("original", "")}"</p>
            <p class="korean">"{quote.get("korean", "")}"</p>
        </blockquote>'''

    actions_html = "".join([f'<li>{item}</li>' for item in summary.get('action_items', [])])
    topics_html = "".join([f'<span class="topic">{t}</span>' for t in summary.get('related_topics', [])])

    # 번역문 문단 처리
    korean_paragraphs = "".join([f'<p>{p.strip()}</p>' for p in korean.split('\n\n') if p.strip()])

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{summary.get("one_liner", "YouTube 번역")}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.8;
            color: #333;
            background: #f8f9fa;
        }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 40px 20px; }}

        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 20px;
            margin-bottom: 30px;
            border-radius: 16px;
        }}
        header h1 {{ font-size: 1.8em; margin-bottom: 16px; }}
        .meta {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
        .difficulty {{
            background: rgba(255,255,255,0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
        }}
        .video-link {{
            color: white;
            text-decoration: none;
            background: rgba(255,255,255,0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
        }}
        .video-link:hover {{ background: rgba(255,255,255,0.3); }}

        .tags {{ margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap; }}
        .tag {{
            background: rgba(255,255,255,0.25);
            padding: 4px 12px;
            border-radius: 16px;
            font-size: 0.85em;
        }}

        section {{
            background: white;
            padding: 30px;
            margin-bottom: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        section h2 {{
            font-size: 1.3em;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
            color: #444;
        }}

        .key-point {{
            margin-bottom: 24px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        .key-point:last-child {{ margin-bottom: 0; }}
        .key-point h4 {{ color: #667eea; margin-bottom: 8px; font-size: 1.1em; }}
        .key-point p {{ color: #555; }}
        .key-point .example {{
            margin-top: 12px;
            padding: 12px;
            background: #e9ecef;
            border-radius: 6px;
            font-size: 0.9em;
            color: #666;
        }}

        .quote {{
            margin-bottom: 20px;
            padding: 20px;
            background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
            border-radius: 8px;
            border: none;
        }}
        .quote:last-child {{ margin-bottom: 0; }}
        .quote .original {{
            font-style: italic;
            color: #666;
            margin-bottom: 8px;
            font-size: 0.95em;
        }}
        .quote .korean {{
            color: #333;
            font-weight: 500;
            font-size: 1.05em;
        }}

        .actions {{ padding-left: 20px; }}
        .actions li {{
            margin-bottom: 12px;
            color: #444;
            position: relative;
            padding-left: 8px;
        }}
        .actions li::marker {{ color: #667eea; }}

        .topics {{ display: flex; gap: 10px; flex-wrap: wrap; }}
        .topic {{
            background: #e9ecef;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.9em;
            color: #555;
        }}

        .transcript {{
            max-height: 400px;
            overflow-y: auto;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }}
        .transcript p {{ margin-bottom: 16px; color: #444; }}
        .transcript p:last-child {{ margin-bottom: 0; }}

        .collapse-btn {{
            background: #667eea;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.95em;
            margin-bottom: 16px;
        }}
        .collapse-btn:hover {{ background: #5a6fd6; }}
        .collapsed {{ display: none; }}

        footer {{
            text-align: center;
            padding: 20px;
            color: #888;
            font-size: 0.85em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{summary.get("one_liner", "YouTube 번역")}</h1>
            <div class="meta">
                <span class="difficulty">{summary.get("difficulty", "중급")}</span>
                <a href="https://www.youtube.com/watch?v={video_id}" target="_blank" class="video-link">YouTube에서 보기</a>
            </div>
            <div class="tags">{tags_html}</div>
        </header>

        <section>
            <h2>핵심 포인트</h2>
            {key_points_html}
        </section>

        <section>
            <h2>인용구</h2>
            {quotes_html}
        </section>

        <section>
            <h2>액션 아이템</h2>
            <ul class="actions">{actions_html}</ul>
        </section>

        <section>
            <h2>연관 주제</h2>
            <div class="topics">{topics_html}</div>
        </section>

        <section>
            <h2>전체 번역</h2>
            <button class="collapse-btn" onclick="toggleTranscript()">펼치기 / 접기</button>
            <div class="transcript" id="transcript">{korean_paragraphs}</div>
        </section>

        <footer>
            <p>Generated by YouTube 번역 에이전트 | {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
        </footer>
    </div>
    <script>
        function toggleTranscript() {{
            document.getElementById('transcript').classList.toggle('collapsed');
        }}
    </script>
</body>
</html>'''


def process_video(job_id: str, url: str):
    """백그라운드에서 영상 처리"""
    try:
        jobs[job_id]["status"] = "processing"

        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")

        client = anthropic.Anthropic(api_key=api_key)

        # 1. Video ID 추출
        video_id = extract_video_id(url)
        jobs[job_id]["video_id"] = video_id
        jobs[job_id]["step"] = "자막 추출 중..."

        # 2. 자막 추출
        original = extract_transcript(video_id)
        jobs[job_id]["step"] = "번역 중..."

        # 3. 번역
        korean = translate(client, original)
        jobs[job_id]["step"] = "요약 중..."

        # 4. 요약
        summary = summarize(client, korean)
        jobs[job_id]["step"] = "저장 중..."

        # 5. 저장
        OUTPUT_DIR.mkdir(exist_ok=True)

        result = {
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "original_transcript": original,
            "korean_transcript": korean,
            "summary": summary,
            "processed_at": datetime.now().isoformat()
        }

        # JSON 저장
        json_path = OUTPUT_DIR / f"{video_id}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # HTML 저장
        html_content = generate_html(video_id, korean, summary)
        html_path = OUTPUT_DIR / f"{video_id}.html"
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result
        jobs[job_id]["html_path"] = str(html_path)

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


@app.get("/", response_class=HTMLResponse)
async def index():
    """메인 페이지"""
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/translate")
async def start_translation(request: TranslateRequest, background_tasks: BackgroundTasks):
    """번역 작업 시작"""
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "video_id": None,
        "step": "대기 중...",
        "error": None,
        "result": None
    }
    background_tasks.add_task(process_video, job_id, request.url)
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """작업 상태 확인"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return jobs[job_id]


@app.get("/api/result/{video_id}")
async def get_result(video_id: str):
    """결과 조회"""
    json_path = OUTPUT_DIR / f"{video_id}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다.")
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


@app.get("/view/{video_id}", response_class=HTMLResponse)
async def view_result(video_id: str):
    """HTML 결과 페이지"""
    html_path = OUTPUT_DIR / f"{video_id}.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다.")
    return FileResponse(html_path)


@app.get("/api/list")
async def list_results():
    """저장된 결과 목록"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    results = []
    for json_file in OUTPUT_DIR.glob("*.json"):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            results.append({
                "video_id": data.get("video_id"),
                "one_liner": data.get("summary", {}).get("one_liner", ""),
                "tags": data.get("summary", {}).get("tags", []),
                "processed_at": data.get("processed_at")
            })
    return sorted(results, key=lambda x: x.get("processed_at", ""), reverse=True)


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 디렉토리 생성"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
