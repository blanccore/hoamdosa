"""
pexels_downloader.py — Pexels 이미지 다운로드 모듈
검색어로 Pexels에서 이미지를 검색하고 다운로드한다.
"""

import os
import requests
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def search_and_download(
    query: str,
    output_dir: str,
    count: int = 1,
    size: str = "medium",
) -> list[str]:
    """
    Pexels에서 이미지를 검색하고 다운로드한다.

    Args:
        query: 검색어 (영어)
        output_dir: 다운로드 디렉토리
        count: 다운로드할 이미지 수
        size: 이미지 크기 (small, medium, large, original)

    Returns:
        다운로드된 파일 경로 리스트
    """
    if not PEXELS_API_KEY:
        raise RuntimeError("[PEXELS] PEXELS_API_KEY가 설정되지 않았습니다")

    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": count, "orientation": "landscape"}

    response = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"[PEXELS] 검색 에러 ({response.status_code})")

    data = response.json()
    photos = data.get("photos", [])

    if not photos:
        print(f"[PEXELS] '{query}' 검색 결과 없음")
        return []

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    downloaded = []

    for i, photo in enumerate(photos[:count]):
        # 크기별 URL
        src = photo.get("src", {})
        url = src.get(size, src.get("medium", ""))

        if not url:
            continue

        # 다운로드
        safe_query = "".join(c if c.isalnum() else "_" for c in query)[:30]
        filename = f"{safe_query}_{photo['id']}.jpg"
        filepath = str(Path(output_dir) / filename)

        img_resp = requests.get(url, timeout=30)
        if img_resp.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(img_resp.content)
            downloaded.append(filepath)
            print(f"[PEXELS] ✅ {filename} ({len(img_resp.content)//1024}KB)")

    return downloaded


def download_for_keywords(
    keywords_result: list[dict],
    output_dir: str,
    images_per_sentence: int = 1,
) -> list[dict]:
    """
    keyword_generator 결과에서 각 문장별 이미지를 다운로드한다.

    Args:
        keywords_result: [{"sentence": str, "keywords": list[str]}, ...]
        output_dir: 다운로드 디렉토리
        images_per_sentence: 문장당 이미지 수

    Returns:
        [{"sentence": str, "keywords": list, "images": list[str]}, ...]
    """
    results = []
    for i, item in enumerate(keywords_result):
        images = []
        for keyword in item.get("keywords", [])[:1]:  # 첫 번째 키워드로 검색
            try:
                paths = search_and_download(
                    query=keyword,
                    output_dir=output_dir,
                    count=images_per_sentence,
                )
                images.extend(paths)
            except Exception as e:
                print(f"[PEXELS] 다운로드 실패 ({keyword}): {e}")

        results.append({
            "sentence": item.get("sentence", ""),
            "keywords": item.get("keywords", []),
            "images": images,
        })

    total = sum(len(r["images"]) for r in results)
    print(f"[PEXELS] ✅ 총 {total}개 이미지 다운로드 완료")
    return results
