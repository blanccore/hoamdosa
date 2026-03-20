"""
silence_remover.py — 무음 감지 & 제거 모듈
FFmpeg silencedetect를 사용하여 오디오/영상에서 무음 구간을 감지하고 제거한다.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional


def detect_silence(
    input_path: str,
    threshold_db: float = -35,
    min_duration: float = 0.5,
) -> list[dict]:
    """
    FFmpeg silencedetect로 무음 구간을 감지한다.

    Args:
        input_path: 입력 오디오/영상 파일 경로
        threshold_db: 무음 판정 임계값 (dB)
        min_duration: 최소 무음 길이 (초)

    Returns:
        무음 구간 리스트 [{"start": float, "end": float, "duration": float}, ...]
    """
    cmd = [
        "ffmpeg", "-i", input_path,
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null", "-"
    ]

    print(f"[SILENCE] 무음 감지 중... (threshold: {threshold_db}dB, min: {min_duration}s)")

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300
    )

    # FFmpeg는 silencedetect 결과를 stderr에 출력
    output = result.stderr

    # 파싱: silence_start, silence_end, silence_duration
    silence_starts = re.findall(r"silence_start:\s*([\d.]+)", output)
    silence_ends = re.findall(r"silence_end:\s*([\d.]+)", output)
    silence_durations = re.findall(r"silence_duration:\s*([\d.]+)", output)

    silences = []
    for i in range(len(silence_ends)):
        start = float(silence_starts[i]) if i < len(silence_starts) else 0.0
        end = float(silence_ends[i])
        duration = float(silence_durations[i]) if i < len(silence_durations) else end - start

        silences.append({
            "start": start,
            "end": end,
            "duration": duration,
        })

    print(f"[SILENCE] 감지된 무음 구간: {len(silences)}개")
    for i, s in enumerate(silences):
        print(f"  [{i+1}] {s['start']:.2f}s ~ {s['end']:.2f}s (duration: {s['duration']:.2f}s)")

    return silences


def get_duration(input_path: str) -> float:
    """미디어 파일의 총 길이를 초 단위로 반환한다."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _build_voice_segments(
    silences: list[dict],
    total_duration: float,
    padding: float = 0.05,
) -> list[dict]:
    """
    무음 구간을 반으로 줄여서 음성 구간을 계산한다.
    무음을 완전히 제거하지 않고, 무음 길이의 절반만 잘라내어
    자연스러운 호흡 간격을 유지한다.

    예: 1.0초 무음 → 0.5초로 축소 (중간 절반만 컷)
    """
    if not silences:
        return [{"start": 0, "end": total_duration}]

    segments = []
    cursor = 0.0

    for silence in silences:
        silence_dur = silence["duration"]
        # 무음의 앞쪽 1/4 유지, 중간 1/2 컷, 뒤쪽 1/4 유지
        keep_front = silence_dur * 0.25
        keep_back = silence_dur * 0.25

        seg_start = cursor
        seg_end = silence["start"] + keep_front

        if seg_end > seg_start + 0.05:
            segments.append({"start": max(0, seg_start), "end": seg_end})

        cursor = silence["end"] - keep_back

    # 마지막 무음 이후 남은 구간
    if cursor < total_duration - 0.05:
        segments.append({"start": max(0, cursor), "end": total_duration})

    return segments


def remove_silence(
    input_path: str,
    output_path: str,
    threshold_db: float = -35,
    min_duration: float = 0.5,
    padding: float = 0.05,
    fade_duration: float = 0.1,
    silences: Optional[list[dict]] = None,
) -> tuple[str, list[dict]]:
    """
    오디오/영상에서 무음 구간을 제거한다.

    Args:
        input_path: 입력 파일 경로
        output_path: 출력 파일 경로
        threshold_db: 무음 판정 임계값 (dB)
        min_duration: 최소 무음 길이 (초)
        padding: 음성 구간 앞뒤 여유 (초)
        silences: 이미 감지된 무음 구간 (없으면 자동 감지)

    Returns:
        (출력 파일 경로, 감지된 무음 구간 리스트)
    """
    if silences is None:
        silences = detect_silence(input_path, threshold_db, min_duration)

    if not silences:
        print("[SILENCE] 무음 구간 없음 — 원본 복사")
        # 무음이 없으면 원본 그대로 복사
        subprocess.run(
            ["cp", input_path, output_path],
            check=True, timeout=60,
        )
        return output_path, silences

    total_duration = get_duration(input_path)
    voice_segments = _build_voice_segments(silences, total_duration, padding)

    print(f"[SILENCE] 음성 구간: {len(voice_segments)}개")
    for i, seg in enumerate(voice_segments):
        print(f"  [{i+1}] {seg['start']:.2f}s ~ {seg['end']:.2f}s")

    # 확장자로 오디오/영상 판별
    ext = Path(input_path).suffix.lower()
    is_video = ext in (".mp4", ".mov", ".avi", ".mkv", ".webm")

    # FFmpeg filter_complex로 비무음 구간만 연결
    filter_parts = []
    concat_inputs = []

    for i, seg in enumerate(voice_segments):
        start = seg["start"]
        end = seg["end"]
        seg_dur = end - start

        # 각 구간별 fade in/out 적용 (숨소리 제거)
        # fade out 시작 시간 = 구간 길이 - fade_duration
        fade_out_start = max(0, seg_dur - fade_duration)

        if is_video:
            filter_parts.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={fade_duration},"
                f"afade=t=out:st={fade_out_start}:d={fade_duration}[a{i}];"
            )
            concat_inputs.append(f"[v{i}][a{i}]")
        else:
            filter_parts.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={fade_duration},"
                f"afade=t=out:st={fade_out_start}:d={fade_duration}[a{i}];"
            )
            concat_inputs.append(f"[a{i}]")

    n = len(voice_segments)
    if is_video:
        concat = "".join(concat_inputs) + f"concat=n={n}:v=1:a=1[outv][outa]"
        filter_complex = "".join(filter_parts) + concat
        map_args = ["-map", "[outv]", "-map", "[outa]"]
    else:
        concat = "".join(concat_inputs) + f"concat=n={n}:v=0:a=1[outa]"
        filter_complex = "".join(filter_parts) + concat
        map_args = ["-map", "[outa]"]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    out_ext = Path(output_path).suffix.lower()

    if is_video:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-filter_complex", filter_complex,
            *map_args,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
    else:
        # 오디오 전용: 출력 확장자에 맞는 코덱 사용
        if out_ext == ".mp3":
            audio_codec = ["-c:a", "libmp3lame", "-b:a", "192k"]
        elif out_ext in (".m4a", ".aac"):
            audio_codec = ["-c:a", "aac", "-b:a", "192k"]
        else:
            audio_codec = ["-c:a", "libmp3lame", "-b:a", "192k"]

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-filter_complex", filter_complex,
            *map_args,
            *audio_codec,
            output_path,
        ]

    print(f"[SILENCE] 무음 제거 실행 중...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"[SILENCE] FFmpeg 에러:\n{result.stderr[-500:]}")

    original_dur = total_duration
    new_dur = get_duration(output_path)
    removed = original_dur - new_dur

    print(f"[SILENCE] ✅ 완료: {original_dur:.1f}s → {new_dur:.1f}s (제거: {removed:.1f}s)")
    print(f"[SILENCE] 출력: {output_path}")

    return output_path, silences
