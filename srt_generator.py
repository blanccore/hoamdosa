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


def generate_srt_with_script(
    audio_path: str,
    script_text: str,
    output_path: str = None,
    language: str = "ko",
) -> str:
    """
    대본 기반 SRT 생성.
    Whisper word-level 타임스탬프로 정확한 싱크를 맞춘다.
    """
    import re
    import requests

    if not output_path:
        output_path = str(Path(audio_path).with_suffix(".srt"))

    print(f"[SRT] 대본 기반 SRT 생성 중: {Path(audio_path).name}")

    # 1. 대본을 문장으로 분리 (줄바꿈만 기준)
    sentences = [s.strip() for s in script_text.split("\n") if s.strip() and len(s.strip()) > 1]

    if not sentences:
        print("[SRT] 대본이 비어있음, 일반 모드로 전환")
        return generate_srt(audio_path, output_path, language)

    # 2. Whisper word-level 타임스탬프
    if not OPENAI_API_KEY:
        return generate_srt(audio_path, output_path, language)

    with open(audio_path, "rb") as f:
        response = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": (Path(audio_path).name, f, "audio/mpeg")},
            data={
                "model": "whisper-1",
                "response_format": "verbose_json",
                "timestamp_granularities[]": "word",
                "language": language,
            },
            timeout=300,
        )

    if response.status_code != 200:
        print(f"[SRT] Whisper API 에러 ({response.status_code}), 일반 모드로 전환")
        return generate_srt(audio_path, output_path, language)

    result = response.json()
    words = result.get("words", [])

    if not words:
        # word 타임스탬프 없으면 segment 기반 fallback
        print("[SRT] word 타임스탬프 없음, segment 기반 fallback")
        return generate_srt(audio_path, output_path, language)

    # 3. 대본 문장별로 Whisper words를 순차 매칭 (글자수 기반)
    total_script_chars = sum(len(s.replace(" ", "")) for s in sentences)
    total_words = len(words)

    matched_segments = []
    word_idx = 0

    for sentence in sentences:
        # 이 문장이 차지할 단어 수 (글자수 비례)
        sentence_chars = len(sentence.replace(" ", ""))
        ratio = sentence_chars / total_script_chars
        n_words_for_sentence = max(1, round(total_words * ratio))

        # 단어 범위 할당
        start_word_idx = word_idx
        end_word_idx = min(word_idx + n_words_for_sentence - 1, len(words) - 1)

        # 마지막 문장은 남은 단어 모두 할당
        if sentence == sentences[-1]:
            end_word_idx = len(words) - 1

        if start_word_idx < len(words):
            matched_segments.append({
                "start": words[start_word_idx]["start"],
                "end": words[end_word_idx]["end"],
                "text": sentence,
            })

        word_idx = end_word_idx + 1

    # 4. SRT 생성 (분할 적용)
    srt_content = _segments_to_srt(matched_segments)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    print(f"[SRT] ✅ 대본 기반 완료: {len(matched_segments)}문장, {len(words)} words → {output_path}")
    return output_path


def _split_segment(seg: dict) -> list[dict]:
    """긴 세그먼트를 반으로 나눈다. 쉴표+공백 우선, 그다음 공백."""
    text = seg.get("text", "").strip()
    start = seg["start"]
    end = seg["end"]

    # 짧으면 그대로
    if len(text) <= 25:
        return [seg]

    mid = len(text) * 2 // 5  # 40% 지점 (앞쪽 짧게)

    # 1순위: 쉼표+공백 뒤에서 자르기
    best_pos = None
    for offset in range(0, len(text) // 2):
        for pos in [mid - offset, mid + offset]:
            if 1 < pos < len(text) and text[pos - 1] == "," and text[pos] == " ":
                best_pos = pos + 1
                break
        if best_pos is not None:
            break

    # 2순위: 일반 공백 (앞쪽 우선)
    if best_pos is None:
        for offset in range(0, min(mid, 20)):
            for pos in [mid - offset, mid + offset]:
                if 0 < pos < len(text) and text[pos] == " ":
                    best_pos = pos
                    break
            if best_pos is not None:
                break

    if best_pos is None:
        return [seg]

    text1 = text[:best_pos].strip()
    text2 = text[best_pos:].strip()

    if not text1 or not text2:
        return [seg]

    ratio = len(text1) / len(text)
    mid_time = start + (end - start) * ratio

    seg1 = {"start": start, "end": mid_time, "text": text1}
    seg2 = {"start": mid_time, "end": end, "text": text2}

    # 재귀: 나뉜 결과도 길면 다시 나누기
    return _split_segment(seg1) + _split_segment(seg2)


def _clean_text(text):
    """자막 텍스트에서 쉼표, 온점 제거"""
    import re
    text = text.replace(",", "").replace(".", "").replace("\uff0c", "").replace("\u3002", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _segments_to_srt(segments: list) -> str:
    """Whisper segments를 SRT 형식으로 변환 (긴 구간은 반으로 분할)"""
    # 모든 세그먼트를 반으로 나누기
    split_segments = []
    for seg in segments:
        split_segments.extend(_split_segment(seg))

    lines = []
    for i, seg in enumerate(split_segments, 1):
        start = _format_timestamp(seg["start"])
        end = _format_timestamp(seg["end"])
        text = _clean_text(seg.get("text", ""))
        if not text:
            continue
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)
