"""
srt_generator.py — Whisper 기반 SRT 자막 생성 모듈
음성 파일에서 타이밍 맞춘 SRT 자막 파일을 생성한다.
Whisper API (OpenAI) 우선, 실패 시 로컬 Whisper fallback.
"""

import os
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def _format_timestamp(seconds: float) -> str:
    """초를 SRT 타임스탬프 형식으로 변환 (HH:MM:SS,mmm)"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt_api(audio_path: str, output_path: str = None, language: str = "ko") -> str:
    """
    OpenAI Whisper API로 SRT 자막을 생성한다.

    Args:
        audio_path: 음성 파일 경로
        output_path: SRT 출력 경로 (없으면 자동 생성)
        language: 언어 코드

    Returns:
        SRT 파일 경로
    """
    import requests

    if not OPENAI_API_KEY:
        raise RuntimeError("[SRT] OPENAI_API_KEY가 설정되지 않았습니다")

    if not output_path:
        output_path = str(Path(audio_path).with_suffix(".srt"))

    print(f"[SRT] Whisper API 자막 생성 중: {Path(audio_path).name}")

    # 파일 크기 확인 (25MB 제한)
    file_size = os.path.getsize(audio_path)
    if file_size > 25 * 1024 * 1024:
        print(f"[SRT] 파일이 25MB 초과 ({file_size/1024/1024:.1f}MB), 분할 필요")
        return _generate_srt_chunked(audio_path, output_path, language)

    with open(audio_path, "rb") as f:
        response = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": (Path(audio_path).name, f, "audio/mpeg")},
            data={
                "model": "whisper-1",
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
                "language": language,
            },
            timeout=300,
        )

    if response.status_code != 200:
        raise RuntimeError(f"[SRT] Whisper API 에러 ({response.status_code}): {response.text[:200]}")

    result = response.json()
    segments = result.get("segments", [])

    # SRT 생성
    srt_content = _segments_to_srt(segments)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    print(f"[SRT] ✅ 완료: {len(segments)}개 구간, {output_path}")
    return output_path


def _generate_srt_chunked(audio_path: str, output_path: str, language: str) -> str:
    """25MB 초과 파일을 10분 단위로 분할하여 처리"""
    import subprocess

    # 전체 길이 확인
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        capture_output=True, text=True, timeout=30,
    )
    total_duration = float(result.stdout.strip())

    chunk_duration = 600  # 10분
    all_segments = []
    offset = 0.0
    chunk_idx = 0

    while offset < total_duration:
        chunk_path = f"/tmp/whisper_chunk_{chunk_idx}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path,
             "-ss", str(offset), "-t", str(chunk_duration),
             "-c:a", "libmp3lame", "-b:a", "128k", chunk_path],
            capture_output=True, timeout=300,
        )

        try:
            import requests
            with open(chunk_path, "rb") as f:
                response = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    files={"file": (f"chunk_{chunk_idx}.mp3", f, "audio/mpeg")},
                    data={
                        "model": "whisper-1",
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment",
                        "language": language,
                    },
                    timeout=300,
                )

            if response.status_code == 200:
                segments = response.json().get("segments", [])
                # 오프셋 적용
                for seg in segments:
                    seg["start"] += offset
                    seg["end"] += offset
                all_segments.extend(segments)
        finally:
            os.remove(chunk_path)

        offset += chunk_duration
        chunk_idx += 1

    srt_content = _segments_to_srt(all_segments)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    print(f"[SRT] ✅ 분할 처리 완료: {len(all_segments)}개 구간")
    return output_path


def generate_srt_local(audio_path: str, output_path: str = None, language: str = "ko") -> str:
    """
    로컬 Whisper로 SRT 자막을 생성한다 (fallback).
    """
    try:
        import whisper
    except ImportError:
        raise RuntimeError("[SRT] whisper 패키지 없음: pip install openai-whisper")

    if not output_path:
        output_path = str(Path(audio_path).with_suffix(".srt"))

    print(f"[SRT] 로컬 Whisper 자막 생성 중: {Path(audio_path).name}")

    model = whisper.load_model("base")
    result = model.transcribe(audio_path, language=language)
    segments = result.get("segments", [])

    srt_content = _segments_to_srt(segments)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    print(f"[SRT] ✅ 로컬 완료: {len(segments)}개 구간")
    return output_path


def generate_srt(audio_path: str, output_path: str = None, language: str = "ko") -> str:
    """
    SRT 생성 (API 우선, 실패 시 로컬 fallback).
    """
    # API 우선 시도
    if OPENAI_API_KEY:
        try:
            return generate_srt_api(audio_path, output_path, language)
        except Exception as e:
            print(f"[SRT] API 실패, 로컬 fallback: {e}")

    # 로컬 fallback
    return generate_srt_local(audio_path, output_path, language)


def _segments_to_srt(segments: list) -> str:
    """Whisper segments를 SRT 형식으로 변환"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_timestamp(seg["start"])
        end = _format_timestamp(seg["end"])
        text = seg.get("text", "").strip()
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)
