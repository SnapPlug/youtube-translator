# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Alex is a YouTube content archiving system that automatically extracts, translates, and organizes YouTube content (primarily Alex Hormozi videos) into a Korean language archive. The system uses n8n for workflow orchestration, Claude API for translation/summarization, and Supabase for storage.

## Architecture

The system consists of 4 core skills executed in sequence:

1. **Transcript Extractor** - Extracts subtitles from YouTube URLs using `youtube-transcript-api`
2. **Translator** - Translates English transcripts to natural Korean (의역 preferred over 직역)
3. **Content Summarizer** - Structures translated content into key points, quotes, action items
4. **Archiver** - Stores processed content in Supabase `alex_contents` table

### Workflow Flow
```
Webhook/RSS → Validate URL → Extract Transcript → Claude Translate → Claude Summarize → Supabase
```

## Tech Stack

- **Workflow**: n8n
- **AI**: Claude API (claude-sonnet-4-20250514)
- **Database**: Supabase (PostgreSQL)
- **Transcript**: youtube-transcript-api (Python)
- **Frontend**: Next.js (planned)

## Quick Test Commands

```python
# Test transcript extraction
from youtube_transcript_api import YouTubeTranscriptApi
transcript = YouTubeTranscriptApi.get_transcript("VIDEO_ID")
```

```bash
# Test Claude API
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model": "claude-sonnet-4-20250514", "max_tokens": 4096, ...}'
```

## Translation Guidelines

When working with translation prompts:
- Prioritize meaning over literal translation (의역 우선)
- Use Korean business terminology: "leverage" → "활용하다", "scale" → "규모를 키우다"
- Maintain conversational tone from video
- Keep proper nouns in original form (Alex Hormozi, Acquisition.com)

## Database Schema

Main table: `alex_contents`
- Key fields: `video_id` (unique), `original_transcript`, `korean_transcript`
- Structured summary: `one_liner`, `tags[]`, `difficulty`, `key_points` (JSONB), `quotes` (JSONB), `action_items[]`
- Status tracking: `status` (pending/processing/completed/failed)

## Content Summarizer Output Schema

```json
{
  "one_liner": "30자 이내 요약",
  "tags": ["태그1", "태그2"],
  "difficulty": "입문|중급|고급",
  "keywords": ["키워드1"],
  "key_points": [{"title": "", "description": "", "example": ""}],
  "quotes": [{"original": "", "korean": ""}],
  "action_items": ["액션1"],
  "related_topics": ["주제1"]
}
```
