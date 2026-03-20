"""
keyword_generator.py — 이미지 검색어 생성 모듈
Gemini AI로 스크립트 문장별 이미지 검색어를 생성한다.
"""

import os
import json

from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def generate_keywords(
    sentences: list[str],
    model_name: str = "gemini-2.5-flash",
) -> list[dict]:
    """
    문장별 이미지 검색어를 생성한다.

    Args:
        sentences: 스크립트 문장 리스트
        model_name: Gemini 모델 이름

    Returns:
        [{"sentence": str, "keywords": list[str]}, ...]
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("[KEYWORD] GEMINI_API_KEY가 설정되지 않았습니다")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # 문장 리스트를 번호 매겨서 전달
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))

    prompt = f"""다음 스크립트의 각 문장에 어울리는 **영어 이미지 검색어**를 2-3개씩 생성해주세요.
검색어는 Pexels, Unsplash 등 스톡 이미지 사이트에서 검색할 수 있는 구체적인 영어 키워드여야 합니다.

반드시 아래 JSON 형식으로만 답변하세요 (설명 없이):
[
  {{"sentence_num": 1, "keywords": ["keyword1", "keyword2", "keyword3"]}},
  {{"sentence_num": 2, "keywords": ["keyword1", "keyword2"]}}
]

스크립트:
{numbered}"""

    print(f"[KEYWORD] Gemini 검색어 생성 중... ({len(sentences)}문장)")

    # 3회 재시도
    response = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            break
        except Exception as e:
            if attempt < 2:
                import time
                wait = 2 * (attempt + 1)
                print(f"[KEYWORD] API 에러 ({attempt+1}/3), {wait}초 후 재시도: {e}")
                time.sleep(wait)
            else:
                raise

    # JSON 파싱
    text = response.text.strip()
    # ```json ... ``` 블록 제거
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    keyword_list = json.loads(text)

    # 결과 조합
    results = []
    for i, sentence in enumerate(sentences):
        keywords = []
        for item in keyword_list:
            if item.get("sentence_num") == i + 1:
                keywords = item.get("keywords", [])
                break
        results.append({
            "sentence": sentence,
            "keywords": keywords,
        })

    print(f"[KEYWORD] ✅ 생성 완료!")
    for r in results:
        print(f"  [{', '.join(r['keywords'])}] {r['sentence'][:40]}...")

    return results


def format_keywords_text(results: list[dict]) -> str:
    """검색어 결과를 텍스트로 포맷한다."""
    lines = []
    for i, r in enumerate(results):
        kw = ", ".join(r["keywords"]) if r["keywords"] else "N/A"
        lines.append(f"{i+1}. 🔍 {kw}")
        lines.append(f"   📝 {r['sentence'][:60]}")
        lines.append("")
    return "\n".join(lines)
