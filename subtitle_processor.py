"""
subtitle_processor.py — 자막 교정 & 번인 모듈
SRT 자막을 원본 스크립트와 대조 교정 후 영상에 하드코딩한다.
"""

import os
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional


def parse_srt(srt_path: str) -> list[dict]:
    """
    SRT 파일을 파싱한다.

    Returns:
        [{"index": int, "start": str, "end": str, "text": str}, ...]
    """
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    blocks = re.split(r"\n\n+", content)
    subtitles = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        index = int(lines[0].strip())
        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
            lines[1].strip(),
        )
        if not time_match:
            continue

        text = "\n".join(lines[2:]).strip()
        subtitles.append({
            "index": index,
            "start": time_match.group(1),
            "end": time_match.group(2),
            "text": text,
        })

    return subtitles


def correct_subtitles(
    subtitles: list[dict],
    original_script: str,
) -> list[dict]:
    """
    SRT 자막을 원본 스크립트와 SequenceMatcher로 대조 교정한다.

    Args:
        subtitles: 파싱된 자막 리스트
        original_script: 원본 스크립트 전체 텍스트

    Returns:
        교정된 자막 리스트
    """
    # 원본 스크립트에서 문장 단위로 분리
    script_sentences = re.split(r"(?<=[.!?。\n])\s*", original_script.strip())
    script_sentences = [s.strip() for s in script_sentences if s.strip()]

    corrected = []
    script_cursor = 0

    for sub in subtitles:
        sub_text = sub["text"].replace("\n", " ").strip()
        best_ratio = 0
        best_match = sub_text  # fallback: 원본 유지

        # 인접 문장들에서 가장 유사한 것을 찾기
        search_range = range(
            max(0, script_cursor - 2),
            min(len(script_sentences), script_cursor + 5),
        )

        for i in search_range:
            ratio = SequenceMatcher(None, sub_text, script_sentences[i]).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = script_sentences[i]
                if ratio > 0.6:
                    script_cursor = i + 1

        corrected_sub = sub.copy()
        if best_ratio >= 0.5:
            corrected_sub["text"] = best_match
            if best_ratio < 1.0:
                print(f"  [교정] ({best_ratio:.0%}) \"{sub_text[:30]}...\" → \"{best_match[:30]}...\"")
        else:
            corrected_sub["text"] = sub_text
            print(f"  [유지] ({best_ratio:.0%}) \"{sub_text[:30]}...\"")

        corrected.append(corrected_sub)

    return corrected


def write_srt(subtitles: list[dict], output_path: str) -> str:
    """교정된 자막을 SRT 파일로 저장한다."""
    lines = []
    for sub in subtitles:
        lines.append(str(sub["index"]))
        lines.append(f"{sub['start']} --> {sub['end']}")
        lines.append(sub["text"])
        lines.append("")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[SUB] ✅ SRT 저장: {output_path}")
    return output_path


def _generate_ass_header(
    fontsize: int = 48,
    outline_width: int = 3,
    video_width: int = 1080,
    video_height: int = 1920,
) -> str:
    """ASS 자막 헤더를 생성한다."""
    return f"""[Script Info]
Title: Hoamdosa Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline_width},2,2,30,30,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _srt_time_to_ass(srt_time: str) -> str:
    """SRT 시간 형식 -> ASS 시간 형식 변환."""
    # 00:00:01,500 -> 0:00:01.50
    parts = srt_time.replace(",", ".").split(":")
    h = int(parts[0])
    m = parts[1]
    s_ms = parts[2][:5]  # 초.밀리초 (2자리)
    return f"{h}:{m}:{s_ms}"


def srt_to_ass(subtitles: list[dict], output_path: str, **kwargs) -> str:
    """SRT 자막을 ASS 형식으로 변환한다."""
    ass_content = _generate_ass_header(**kwargs)

    for sub in subtitles:
        start = _srt_time_to_ass(sub["start"])
        end = _srt_time_to_ass(sub["end"])
        text = sub["text"].replace("\n", "\\N")
        ass_content += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    print(f"[SUB] ✅ ASS 저장: {output_path}")
    return output_path


def burn_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
) -> str:
    """
    ASS 자막을 영상에 하드코딩(번인)한다.

    Args:
        video_path: 입력 영상 파일
        ass_path: ASS 자막 파일
        output_path: 출력 영상 파일

    Returns:
        출력 파일 경로
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # ASS 파일 경로에서 특수문자 이스케이프 (FFmpeg filter용)
    escaped_ass = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"ass='{escaped_ass}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        output_path,
    ]

    print(f"[SUB] 자막 번인 중...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"[SUB] FFmpeg 에러:\n{result.stderr[-500:]}")

    print(f"[SUB] ✅ 자막 번인 완료: {output_path}")
    return output_path


def process_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    original_script_path: Optional[str] = None,
    fontsize: int = 48,
    outline_width: int = 3,
) -> str:
    """
    자막 처리 전체 파이프라인: 교정 → ASS 변환 → 번인

    Args:
        video_path: 입력 영상
        srt_path: SRT 자막 파일
        output_path: 출력 영상
        original_script_path: 원본 스크립트 (없으면 교정 스킵)
        fontsize: 자막 폰트 크기
        outline_width: 자막 외곽선 두께

    Returns:
        출력 파일 경로
    """
    print(f"[SUB] 자막 처리 시작...")

    # 1. SRT 파싱
    subtitles = parse_srt(srt_path)
    print(f"[SUB] 자막 {len(subtitles)}개 로드")

    # 2. 교정 (원본 스크립트가 있을 때만)
    if original_script_path and os.path.exists(original_script_path):
        print(f"[SUB] 원본 스크립트로 교정 중...")
        with open(original_script_path, "r", encoding="utf-8") as f:
            original_script = f.read()
        subtitles = correct_subtitles(subtitles, original_script)
    else:
        print(f"[SUB] 원본 스크립트 없음 — 교정 스킵")

    # 3. ASS 변환
    ass_dir = Path(output_path).parent
    ass_path = str(ass_dir / "subtitles_corrected.ass")
    srt_to_ass(subtitles, ass_path, fontsize=fontsize, outline_width=outline_width)

    # 교정된 SRT도 저장
    corrected_srt = str(ass_dir / "subtitles_corrected.srt")
    write_srt(subtitles, corrected_srt)

    # 4. 번인
    return burn_subtitles(video_path, ass_path, output_path)
