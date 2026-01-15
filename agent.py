#!/usr/bin/env python3
"""YouTube 콘텐츠 번역 에이전트 - 자막 추출, 번역, 요약을 수행합니다."""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
import anthropic

load_dotenv()

OUTPUT_DIR = Path(__file__).parent / "output"
CLAUDE_MODEL = "claude-sonnet-4-20250514"


def extract_video_id(url: str) -> str:
    """YouTube URL에서 video_id 추출"""
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
    """YouTube 자막 추출"""
    print(f"[1/4] 자막 추출 중... (video_id: {video_id})")
    api = YouTubeTranscriptApi()
    try:
        transcript = api.fetch(video_id, languages=['en', 'en-US', 'ko'])
    except Exception:
        transcript = api.fetch(video_id)

    full_text = " ".join([item.text for item in transcript])
    print(f"      완료: {len(full_text)} 글자")
    return full_text


def translate(client: anthropic.Anthropic, text: str) -> str:
    """영어 스크립트를 한글로 번역"""
    print("[2/4] 한글 번역 중...")

    system_prompt = """당신은 전문 번역가입니다. 비즈니스/자기계발 콘텐츠를 한국 독자가 자연스럽게 읽을 수 있도록 번역합니다.

## 번역 원칙
1. **의역 우선**: 직역보다 의미 전달을 우선합니다
2. **비즈니스 용어**: 한국에서 통용되는 표현으로 변환
   - "leverage" → "활용하다"
   - "scale" → "규모를 키우다" / "확장하다"
   - "offer" → "제안" / "상품" (맥락에 따라)
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

    result = response.content[0].text
    print(f"      완료: {len(result)} 글자")
    return result


def summarize(client: anthropic.Anthropic, korean_text: str) -> dict:
    """번역된 콘텐츠를 구조화하여 요약"""
    print("[3/4] 콘텐츠 요약 중...")

    system_prompt = """당신은 콘텐츠 에디터입니다. 비즈니스 콘텐츠를 분석하고 구조화합니다.

## 분석 프레임워크
1. 한 줄 요약 (30자 이내)
2. 핵심 주제 태그 (3-5개)
3. 난이도: 입문/중급/고급
4. 핵심 내용 (3-5개 포인트)
5. 인용구 (임팩트 있는 문장 2-3개, 원문+한글)
6. 액션 아이템 (바로 실행 가능한 행동 1-3개)
7. 연관 주제

## 출력 형식
반드시 아래 JSON 구조로만 응답하세요. 다른 텍스트 없이 JSON만 출력합니다.
{
  "one_liner": "한 줄 요약",
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
    # JSON 파싱 (마크다운 코드블록 제거)
    json_text = re.sub(r'^```json\s*|\s*```$', '', result_text.strip())
    result = json.loads(json_text)
    print("      완료")
    return result


def save_result(video_id: str, original: str, korean: str, summary: dict) -> Path:
    """결과를 JSON 파일로 저장"""
    print("[4/4] 결과 저장 중...")

    OUTPUT_DIR.mkdir(exist_ok=True)

    result = {
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "original_transcript": original,
        "korean_transcript": korean,
        "summary": summary,
        "processed_at": datetime.now().isoformat()
    }

    output_path = OUTPUT_DIR / f"{video_id}.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"      저장 완료: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='YouTube 영상을 번역하고 요약합니다.')
    parser.add_argument('url', help='YouTube URL 또는 video_id')
    args = parser.parse_args()

    # API 키 확인
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("오류: ANTHROPIC_API_KEY 환경변수를 설정해주세요.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    try:
        # 1. Video ID 추출
        video_id = extract_video_id(args.url)
        print(f"\n{'='*50}")
        print(f"YouTube 번역 에이전트 시작")
        print(f"{'='*50}\n")

        # 2. 자막 추출
        original_transcript = extract_transcript(video_id)

        # 3. 번역
        korean_transcript = translate(client, original_transcript)

        # 4. 요약
        summary = summarize(client, korean_transcript)

        # 5. 저장
        output_path = save_result(video_id, original_transcript, korean_transcript, summary)

        print(f"\n{'='*50}")
        print(f"처리 완료!")
        print(f"{'='*50}")
        print(f"\n결과 파일: {output_path}")
        print(f"\n한 줄 요약: {summary.get('one_liner', 'N/A')}")
        print(f"태그: {', '.join(summary.get('tags', []))}")

    except Exception as e:
        print(f"\n오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
