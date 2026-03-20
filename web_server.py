#!/usr/bin/env python3
"""
web_server.py — 호암도사 웹 대시보드 서버
FastAPI 기반 REST API + 정적 웹 프론트엔드

Usage:
    python3 web_server.py
"""

import os
import sys
import asyncio
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

# .env 로드
load_dotenv(Path(__file__).parent / ".env")

# 프로젝트 설정
import json
_CONFIG_PATH = Path(__file__).parent / "project.json"
if _CONFIG_PATH.exists():
    with open(_CONFIG_PATH) as f:
        _CONFIG = json.load(f)
else:
    _CONFIG = {}

SETTINGS = _CONFIG.get("settings", {})

# 디렉토리
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
UPLOAD_DIR = OUTPUT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
IMAGES_DIR = OUTPUT_DIR / "images"
IMAGES_DIR.mkdir(exist_ok=True)

# FastAPI 앱
app = FastAPI(title="호암도사", version="2.0")


# ── API: 상태 ──
@app.get("/api/status")
async def get_status():
    files = [f for f in OUTPUT_DIR.iterdir() if f.is_file()]
    total_size = sum(f.stat().st_size for f in files) / 1024 / 1024
    disk = shutil.disk_usage(str(OUTPUT_DIR))
    return {
        "files_count": len(files),
        "total_size_mb": round(total_size, 1),
        "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
    }


# ── API: 히스토리 ──
@app.get("/api/history")
async def get_history():
    files = sorted(OUTPUT_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    files = [f for f in files if f.is_file() and f.suffix in (".mp3", ".srt")][:20]
    return [
        {
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024),
            "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            "type": f.suffix[1:],
        }
        for f in files
    ]


# ── API: 파일 다운로드 ──
@app.get("/api/download/{filename}")
async def download_file(filename: str):
    filepath = OUTPUT_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="파일 없음")
    return FileResponse(str(filepath), filename=filename)


# ── API: 음성 처리 ──
@app.post("/api/process-audio")
async def process_audio(
    file: UploadFile = File(...),
    speed: float = Form(1.1),
):
    """음성 파일 → 배속 + 무음 편집 + SRT"""
    from silence_remover import remove_silence
    import subprocess

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    input_path = str(UPLOAD_DIR / f"web_{timestamp}_{file.filename}")
    output_path = str(OUTPUT_DIR / f"web_{timestamp}_processed.mp3")

    # 파일 저장
    with open(input_path, "wb") as f:
        content = await file.read()
        f.write(content)

    loop = asyncio.get_event_loop()

    # 배속 처리
    speed_path = str(OUTPUT_DIR / f"web_{timestamp}_speed.mp3")
    await loop.run_in_executor(None, lambda: subprocess.run(
        ["ffmpeg", "-y", "-i", input_path,
         "-filter:a", f"atempo={speed}",
         "-c:a", "libmp3lame", "-b:a", "192k", speed_path],
        capture_output=True, timeout=600,
    ))
    os.remove(input_path)

    # 무음 처리
    final_path, silences = await loop.run_in_executor(
        None,
        lambda: remove_silence(
            input_path=speed_path,
            output_path=output_path,
            threshold_db=SETTINGS.get("silence_threshold", -35),
            min_duration=SETTINGS.get("silence_min_duration", 0.5),
        ),
    )
    # 중간 파일 정리
    if os.path.exists(speed_path):
        os.remove(speed_path)

    # SRT 생성
    srt_path = None
    try:
        from srt_generator import generate_srt
        srt_output = str(OUTPUT_DIR / f"web_{timestamp}.srt")
        srt_path = await loop.run_in_executor(
            None, lambda: generate_srt(final_path, srt_output)
        )
    except Exception:
        pass

    from silence_remover import get_duration
    orig_dur = get_duration(speed_path) if os.path.exists(speed_path) else 0
    new_dur = get_duration(final_path)

    return {
        "audio": f"/api/download/{Path(final_path).name}",
        "srt": f"/api/download/{Path(srt_path).name}" if srt_path else None,
        "duration": round(new_dur, 1),
        "silences_count": len(silences),
        "speed": speed,
    }


# ── API: 유튜브 스크립트 ──
@app.post("/api/youtube-script")
async def youtube_script(url: str = Form(...)):
    """유튜브 URL → 스크립트 + 검색어"""
    from script_extractor import extract_script
    from keyword_generator import generate_keywords, format_keywords_text

    loop = asyncio.get_event_loop()

    result = await loop.run_in_executor(None, lambda: extract_script(url))

    keywords = await loop.run_in_executor(
        None, lambda: generate_keywords(result["sentences"])
    )

    return {
        "title": result["title"],
        "script": result["script"],
        "sentences": result["sentences"],
        "method": result["method"],
        "keywords": keywords,
    }


# ── API: 대본 → 검색어 ──
@app.post("/api/generate-keywords")
async def generate_keywords_api(text: str = Form(...)):
    """텍스트 → 이미지 검색어"""
    import re
    from keyword_generator import generate_keywords, format_keywords_text

    sentences = re.split(r"(?<=[.!?。\n])\s*", text)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 3]

    loop = asyncio.get_event_loop()
    keywords = await loop.run_in_executor(
        None, lambda: generate_keywords(sentences)
    )

    return {"keywords": keywords}


# ── API: Pexels 이미지 ──
@app.post("/api/pexels-download")
async def pexels_download(query: str = Form(...), count: int = Form(3)):
    """검색어 → Pexels 이미지 다운로드"""
    from pexels_downloader import search_and_download

    loop = asyncio.get_event_loop()
    paths = await loop.run_in_executor(
        None, lambda: search_and_download(query, str(IMAGES_DIR), count)
    )

    return {
        "images": [f"/api/download-image/{Path(p).name}" for p in paths],
        "count": len(paths),
    }


@app.get("/api/download-image/{filename}")
async def download_image(filename: str):
    filepath = IMAGES_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="이미지 없음")
    return FileResponse(str(filepath))


# ── 정적 파일 + SPA ──
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/{path:path}")
async def serve_spa(path: str):
    """SPA fallback"""
    file_path = STATIC_DIR / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"🌐 호암도사 대시보드: http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
