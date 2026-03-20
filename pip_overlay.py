"""
pip_overlay.py — PIP 오버레이 모듈 (선택적)
영상 위에 PIP 이미지를 균등 배치하여 오버레이한다.
"""

import subprocess
from pathlib import Path

from silence_remover import get_duration


# PIP 위치 매핑 (화면 내 좌표 계산)
PIP_POSITIONS = {
    "top-left": "x=20:y=20",
    "top-right": "x=main_w-overlay_w-20:y=20",
    "bottom-left": "x=20:y=main_h-overlay_h-20",
    "bottom-right": "x=main_w-overlay_w-20:y=main_h-overlay_h-20",
}


def overlay_pip(
    video_path: str,
    pip_images: list[str],
    output_path: str,
    pip_position: str = "top-left",
    pip_scale: float = 0.30,
    voice_segments: list[dict] | None = None,
) -> str:
    """
    PIP 이미지를 영상에 균등 배치하여 오버레이한다.

    Args:
        video_path: 입력 영상 파일
        pip_images: PIP 이미지 파일 경로 리스트
        output_path: 출력 영상 파일
        pip_position: PIP 위치 (top-left, top-right, bottom-left, bottom-right)
        pip_scale: PIP 크기 비율 (화면 대비)
        voice_segments: 음성 구간 리스트 (없으면 균등 분할)

    Returns:
        출력 파일 경로
    """
    if not pip_images:
        print("[PIP] PIP 이미지 없음 — 스킵")
        subprocess.run(["cp", video_path, output_path], check=True)
        return output_path

    total_duration = get_duration(video_path)
    n_images = len(pip_images)

    # 구간 분할: voice_segments가 있으면 사용, 없으면 균등 분할
    if voice_segments and len(voice_segments) >= n_images:
        segments = voice_segments[:n_images]
        timings = [(seg["start"], seg["end"]) for seg in segments]
    else:
        seg_duration = total_duration / n_images
        timings = [
            (i * seg_duration, (i + 1) * seg_duration)
            for i in range(n_images)
        ]

    position = PIP_POSITIONS.get(pip_position, PIP_POSITIONS["top-left"])

    # FFmpeg filter_complex 구성
    inputs = ["-i", video_path]
    for img in pip_images:
        inputs.extend(["-i", img])

    filter_parts = []
    current_label = "0:v"

    for i, (start, end) in enumerate(timings):
        img_idx = i + 1
        scaled = f"pip{i}"
        out_label = f"v{i}"

        # PIP 이미지 스케일링
        filter_parts.append(
            f"[{img_idx}:v]scale=iw*{pip_scale}:ih*{pip_scale}[{scaled}]"
        )

        # 오버레이 (enable 조건으로 시간 제한)
        enable = f"between(t,{start:.2f},{end:.2f})"
        filter_parts.append(
            f"[{current_label}][{scaled}]overlay={position}:"
            f"enable='{enable}'[{out_label}]"
        )
        current_label = out_label

    filter_complex = ";".join(filter_parts)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{current_label}]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        output_path,
    ]

    print(f"[PIP] 오버레이 중... ({n_images}개 이미지, 위치: {pip_position})")
    for i, (start, end) in enumerate(timings):
        print(f"  [{i+1}] {Path(pip_images[i]).name}: {start:.1f}s ~ {end:.1f}s")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"[PIP] FFmpeg 에러:\n{result.stderr[-500:]}")

    print(f"[PIP] ✅ 오버레이 완료: {output_path}")
    return output_path
