#!/usr/bin/env python3
"""
hoamdosa_editor.py — 호암도사 영상 편집 자동화 v2
대본 → ElevenLabs TTS → 무음 삭제 → (PIP) → 자막 → BGM → 최종 출력

Usage:
    python3 hoamdosa_editor.py --config project.json
    python3 hoamdosa_editor.py --config project.json --dry-run
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

# 모듈 임포트
from tts_generator import generate_tts, generate_tts_from_file
from silence_remover import detect_silence, remove_silence
from subtitle_processor import process_subtitles
from bgm_mixer import mix_bgm
from pip_overlay import overlay_pip


def load_config(config_path: str) -> dict:
    """프로젝트 설정 파일을 로드한다."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 설정 파일 기준 상대 경로를 절대 경로로 변환
    config_dir = Path(config_path).parent.resolve()

    path_keys = [
        "script_file", "heygen_video", "subtitles_srt",
        "original_script", "bgm_file",
    ]
    for key in path_keys:
        if key in config and config[key]:
            p = Path(config[key])
            if not p.is_absolute():
                config[key] = str(config_dir / p)

    # pip_images 경로도 변환
    if "pip_images" in config:
        config["pip_images"] = [
            str(config_dir / p) if not Path(p).is_absolute() else p
            for p in config["pip_images"]
        ]

    # output_dir 처리
    if "output_dir" in config:
        p = Path(config["output_dir"])
        if not p.is_absolute():
            config["output_dir"] = str(config_dir / p)

    return config


def validate_config(config: dict) -> list[str]:
    """설정을 검증하고 문제점 리스트를 반환한다."""
    issues = []

    # 필수 항목 체크
    if not config.get("script_file"):
        issues.append("❌ script_file이 지정되지 않았습니다")
    elif not os.path.exists(config["script_file"]):
        issues.append(f"❌ 스크립트 파일 없음: {config['script_file']}")

    if not config.get("elevenlabs_voice_id"):
        issues.append("❌ elevenlabs_voice_id가 지정되지 않았습니다")

    # API Key 체크
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        issues.append("❌ ELEVENLABS_API_KEY 환경변수가 설정되지 않았습니다")

    # 선택 항목 체크
    if config.get("heygen_video") and not os.path.exists(config["heygen_video"]):
        issues.append(f"⚠️  HeyGen 영상 없음: {config['heygen_video']}")

    if config.get("subtitles_srt") and not os.path.exists(config["subtitles_srt"]):
        issues.append(f"⚠️  자막 파일 없음: {config['subtitles_srt']}")

    if config.get("bgm_file") and not os.path.exists(config["bgm_file"]):
        issues.append(f"⚠️  BGM 파일 없음: {config['bgm_file']}")

    for img in config.get("pip_images", []):
        if not os.path.exists(img):
            issues.append(f"⚠️  PIP 이미지 없음: {img}")

    # FFmpeg 체크
    if not shutil.which("ffmpeg"):
        issues.append("❌ FFmpeg가 설치되지 않았습니다 (brew install ffmpeg)")

    return issues


def dry_run(config: dict):
    """사전 검사를 수행하고 결과를 출력한다."""
    print("=" * 60)
    print("🔍 사전 검사 (Dry Run)")
    print("=" * 60)

    settings = config.get("settings", {})

    print(f"\n📝 스크립트: {config.get('script_file', 'N/A')}")
    print(f"🎥 HeyGen 영상: {config.get('heygen_video', 'N/A')}")
    print(f"🔊 Voice ID: {config.get('elevenlabs_voice_id', 'N/A')}")
    print(f"📋 자막 (SRT): {config.get('subtitles_srt', 'N/A')}")
    print(f"🎵 BGM: {config.get('bgm_file', 'N/A') or '없음'}")
    print(f"🖼️  PIP 이미지: {len(config.get('pip_images', []))}개")
    print(f"📂 출력 디렉토리: {config.get('output_dir', './output')}")

    print(f"\n⚙️  설정:")
    print(f"  무음 임계값: {settings.get('silence_threshold', -35)}dB")
    print(f"  최소 무음 길이: {settings.get('silence_min_duration', 0.5)}s")
    print(f"  BGM 볼륨: {settings.get('bgm_volume', 0.15)}")
    print(f"  자막 크기: {settings.get('subtitle_fontsize', 48)}")
    print(f"  TTS 속도: {settings.get('tts_speed', 0.85)}")

    issues = validate_config(config)
    if issues:
        print(f"\n⚠️  발견된 문제 ({len(issues)}개):")
        for issue in issues:
            print(f"  {issue}")
    else:
        print(f"\n✅ 모든 검사 통과!")

    # 파이프라인 실행 계획
    print(f"\n📋 실행 계획:")
    steps = []
    steps.append("1. 대본 → ElevenLabs TTS 음성 생성")
    steps.append("2. TTS 오디오 무음 구간 감지 & 제거")
    if config.get("heygen_video"):
        steps.append("3. HeyGen 영상 + 무음 제거된 오디오 합성")
    if config.get("pip_images"):
        steps.append("4. PIP 이미지 오버레이")
    if config.get("subtitles_srt"):
        steps.append("5. 자막 처리 (교정 + 번인)")
    if config.get("bgm_file"):
        steps.append("6. BGM 믹싱")
    steps.append("→ 최종 출력")

    for step in steps:
        print(f"  {step}")

    print("=" * 60)
    return len([i for i in issues if i.startswith("❌")]) == 0


def run_pipeline(config: dict):
    """메인 파이프라인을 실행한다."""
    print("=" * 60)
    print("🎬 호암도사 영상 편집 자동화 v2")
    print("=" * 60)

    settings = config.get("settings", {})
    output_dir = config.get("output_dir", "./output")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = config["elevenlabs_voice_id"]

    current_file = None
    silences = None

    # ──────────────────────────────────────────────
    # Step 1: TTS 생성
    # ──────────────────────────────────────────────
    print("\n" + "─" * 40)
    print("📌 Step 1: ElevenLabs TTS 생성")
    print("─" * 40)

    tts_output = os.path.join(output_dir, "01_tts_output.mp3")
    generate_tts_from_file(
        script_path=config["script_file"],
        voice_id=voice_id,
        api_key=api_key,
        output_path=tts_output,
        stability=settings.get("tts_stability", 0.7),
        similarity_boost=settings.get("tts_similarity", 0.8),
        style=settings.get("tts_style", 0.3),
        speed=settings.get("tts_speed", 0.85),
    )
    current_file = tts_output

    # ──────────────────────────────────────────────
    # Step 2: 무음 제거
    # ──────────────────────────────────────────────
    print("\n" + "─" * 40)
    print("📌 Step 2: 무음 감지 & 제거")
    print("─" * 40)

    silence_output = os.path.join(output_dir, "02_silence_removed.mp3")
    current_file, silences = remove_silence(
        input_path=current_file,
        output_path=silence_output,
        threshold_db=settings.get("silence_threshold", -35),
        min_duration=settings.get("silence_min_duration", 0.5),
    )

    # ──────────────────────────────────────────────
    # Step 3: HeyGen 영상과 합성 (있을 경우)
    # ──────────────────────────────────────────────
    heygen_video = config.get("heygen_video")
    if heygen_video and os.path.exists(heygen_video):
        print("\n" + "─" * 40)
        print("📌 Step 3: HeyGen 영상 + 오디오 합성")
        print("─" * 40)

        merged_output = os.path.join(output_dir, "03_merged.mp4")
        _merge_audio_to_video(heygen_video, current_file, merged_output)
        current_file = merged_output
    else:
        print("\n[SKIP] HeyGen 영상 없음 — 오디오만 처리 계속")

    # ──────────────────────────────────────────────
    # Step 4: PIP 오버레이 (선택적)
    # ──────────────────────────────────────────────
    pip_images = config.get("pip_images", [])
    pip_images = [p for p in pip_images if os.path.exists(p)]

    if pip_images and Path(current_file).suffix.lower() in (".mp4", ".mov", ".mkv"):
        print("\n" + "─" * 40)
        print("📌 Step 4: PIP 오버레이")
        print("─" * 40)

        pip_output = os.path.join(output_dir, "04_pip.mp4")
        current_file = overlay_pip(
            video_path=current_file,
            pip_images=pip_images,
            output_path=pip_output,
            pip_position=settings.get("pip_position", "top-left"),
            pip_scale=settings.get("pip_scale", 0.30),
        )
    else:
        print("\n[SKIP] PIP 스킵 (이미지 없음 또는 영상 없음)")

    # ──────────────────────────────────────────────
    # Step 5: 자막 처리 (영상이 있을 때만)
    # ──────────────────────────────────────────────
    srt_path = config.get("subtitles_srt")
    if (
        srt_path
        and os.path.exists(srt_path)
        and Path(current_file).suffix.lower() in (".mp4", ".mov", ".mkv")
    ):
        print("\n" + "─" * 40)
        print("📌 Step 5: 자막 처리")
        print("─" * 40)

        sub_output = os.path.join(output_dir, "05_subtitled.mp4")
        current_file = process_subtitles(
            video_path=current_file,
            srt_path=srt_path,
            output_path=sub_output,
            original_script_path=config.get("original_script"),
            fontsize=settings.get("subtitle_fontsize", 48),
            outline_width=settings.get("subtitle_outline_width", 3),
        )
    else:
        print("\n[SKIP] 자막 스킵 (SRT 없음 또는 영상 없음)")

    # ──────────────────────────────────────────────
    # Step 6: BGM 믹싱
    # ──────────────────────────────────────────────
    bgm_file = config.get("bgm_file")
    if bgm_file and os.path.exists(bgm_file):
        print("\n" + "─" * 40)
        print("📌 Step 6: BGM 믹싱")
        print("─" * 40)

        bgm_output_ext = Path(current_file).suffix
        bgm_output = os.path.join(output_dir, f"06_bgm{bgm_output_ext}")
        current_file = mix_bgm(
            input_path=current_file,
            bgm_path=bgm_file,
            output_path=bgm_output,
            bgm_volume=settings.get("bgm_volume", 0.15),
        )
    else:
        print("\n[SKIP] BGM 스킵 (BGM 파일 없음)")

    # ──────────────────────────────────────────────
    # 최종 출력
    # ──────────────────────────────────────────────
    final_ext = Path(current_file).suffix
    final_output = os.path.join(output_dir, f"final_output{final_ext}")

    if current_file != final_output:
        import shutil as sh
        sh.copy2(current_file, final_output)

    print("\n" + "=" * 60)
    print(f"🎉 완료! 최종 출력: {final_output}")
    print("=" * 60)

    return final_output


def _merge_audio_to_video(video_path: str, audio_path: str, output_path: str) -> str:
    """영상에 새 오디오를 합성한다 (기존 오디오 교체)."""
    import subprocess

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ]

    print(f"[MERGE] 영상 + 오디오 합성 중...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"[MERGE] FFmpeg 에러:\n{result.stderr[-500:]}")

    print(f"[MERGE] ✅ 합성 완료: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="호암도사 영상 편집 자동화 v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python3 hoamdosa_editor.py --config project.json --dry-run
  python3 hoamdosa_editor.py --config project.json
        """,
    )
    parser.add_argument(
        "--config", "-c",
        required=True,
        help="프로젝트 설정 파일 경로 (JSON)",
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="사전 검사만 수행 (실제 실행 안 함)",
    )

    args = parser.parse_args()

    # .env 로드
    env_path = Path(args.config).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # CWD의 .env

    # 설정 로드
    config = load_config(args.config)

    if args.dry_run:
        ok = dry_run(config)
        sys.exit(0 if ok else 1)

    # 검증
    issues = validate_config(config)
    critical = [i for i in issues if i.startswith("❌")]
    if critical:
        print("❌ 치명적 오류:")
        for issue in critical:
            print(f"  {issue}")
        sys.exit(1)

    # 파이프라인 실행
    try:
        run_pipeline(config)
    except Exception as e:
        print(f"\n❌ 파이프라인 에러: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
