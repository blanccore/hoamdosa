"""
script_extractor.py — 유튜브 스크립트 추출 모듈
yt-dlp로 유튜브 영상에서 자막/스크립트를 추출한다.
"""

import json
import re
import subprocess
from pathlib import Path


def extract_script(url: str, output_dir: str = "/tmp") -> dict:
    """
    유튜브 영상에서 스크립트를 추출한다.

    Args:
        url: 유튜브 URL
        output_dir: 임시 출력 디렉토리

    Returns:
        {
            "title": str,
            "url": str,
            "script": str,          # 전체 스크립트 텍스트
            "sentences": list[str],  # 문장 리스트
            "method": str,           # "subtitle" or "auto_subtitle"
        }
    """
    print(f"[SCRIPT] 스크립트 추출 중: {url}")

    # 먼저 영상 정보 가져오기
    info = _get_video_info(url)
    title = info.get("title", "Unknown")
    print(f"[SCRIPT] 제목: {title}")

    # 1차: 수동 자막 시도 (한국어 → 영어)
    script = _try_subtitles(url, output_dir, auto=False)
    method = "subtitle"

    # 2차: 자동 자막 시도
    if not script:
        script = _try_subtitles(url, output_dir, auto=True)
        method = "auto_subtitle"

    if not script:
        raise RuntimeError(f"[SCRIPT] 자막을 찾을 수 없습니다: {url}")

    # 문장 분리
    sentences = _split_sentences(script)

    print(f"[SCRIPT] ✅ 추출 완료: {len(sentences)}문장, {len(script)}자")

    return {
        "title": title,
        "url": url,
        "script": script,
        "sentences": sentences,
        "method": method,
    }


def _get_video_info(url: str) -> dict:
    """영상 기본 정보를 가져온다."""
    cmd = [
        "yt-dlp", "--dump-json", "--no-download", url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return {}
    return json.loads(result.stdout)


def _try_subtitles(url: str, output_dir: str, auto: bool = False) -> str:
    """자막을 다운로드하고 텍스트를 추출한다."""
    sub_flag = "--write-auto-sub" if auto else "--write-sub"
    prefix = Path(output_dir) / "yt_sub"

    cmd = [
        "yt-dlp",
        "--skip-download",
        sub_flag,
        "--sub-langs", "ko,en,ko-orig",
        "--sub-format", "vtt",
        "--convert-subs", "srt",
        "-o", str(prefix),
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    # SRT 파일 찾기
    srt_files = list(Path(output_dir).glob("yt_sub*.srt"))
    if not srt_files:
        return ""

    # 한국어 우선
    srt_path = srt_files[0]
    for f in srt_files:
        if ".ko" in f.name:
            srt_path = f
            break

    # SRT 파싱 → 텍스트만 추출
    script = _srt_to_text(str(srt_path))

    # 임시 파일 정리
    for f in srt_files:
        f.unlink(missing_ok=True)
    # vtt 파일도 정리
    for f in Path(output_dir).glob("yt_sub*.vtt"):
        f.unlink(missing_ok=True)

    return script


def _srt_to_text(srt_path: str) -> str:
    """SRT 파일에서 순수 텍스트를 추출한다."""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    # SRT 타임코드 및 인덱스 제거
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        # 빈 줄, 인덱스 번호, 타임코드 스킵
        if not line:
            continue
        if re.match(r"^\d+$", line):
            continue
        if re.match(r"\d{2}:\d{2}:\d{2}", line):
            continue
        # HTML 태그 제거
        line = re.sub(r"<[^>]+>", "", line)
        if line and line not in lines[-1:]:  # 중복 제거
            lines.append(line)

    return " ".join(lines)


def _split_sentences(text: str) -> list[str]:
    """텍스트를 문장 단위로 분리한다."""
    # 한국어/영어 문장 분리
    sentences = re.split(r"(?<=[.!?。])\s+", text)
    # 빈 문장 제거
    return [s.strip() for s in sentences if s.strip()]
