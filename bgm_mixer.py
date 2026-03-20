"""
bgm_mixer.py — BGM 믹싱 모듈
배경 음악을 영상/오디오에 낮은 볼륨으로 믹싱한다.
"""

import subprocess
from pathlib import Path

from silence_remover import get_duration


def mix_bgm(
    input_path: str,
    bgm_path: str,
    output_path: str,
    bgm_volume: float = 0.15,
) -> str:
    """
    BGM을 영상/오디오에 믹싱한다.

    Args:
        input_path: 입력 파일 (영상 또는 오디오)
        bgm_path: BGM 파일 경로
        output_path: 출력 파일 경로
        bgm_volume: BGM 볼륨 (0.0 ~ 1.0, 기본 0.15)

    Returns:
        출력 파일 경로
    """
    ext = Path(input_path).suffix.lower()
    is_video = ext in (".mp4", ".mov", ".avi", ".mkv", ".webm")

    # 입력 파일 길이로 BGM 자동 루프/트림
    main_duration = get_duration(input_path)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if is_video:
        # 영상: 영상 오디오 + BGM 믹싱
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{main_duration},"
            f"volume={bgm_volume}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=3[outa]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", bgm_path,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            output_path,
        ]
    else:
        # 오디오만: 오디오 + BGM 믹싱
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{main_duration},"
            f"volume={bgm_volume}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=3[outa]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", bgm_path,
            "-filter_complex", filter_complex,
            "-map", "[outa]",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]

    print(f"[BGM] BGM 믹싱 중... (볼륨: {bgm_volume})")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"[BGM] FFmpeg 에러:\n{result.stderr[-500:]}")

    print(f"[BGM] ✅ 믹싱 완료: {output_path}")
    return output_path
