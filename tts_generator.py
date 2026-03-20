"""
tts_generator.py — ElevenLabs TTS 생성 모듈
대본 텍스트를 받아서 호암도사 음성으로 MP3를 생성한다.
"""

import os
import requests
from pathlib import Path


ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"


def generate_tts(
    text: str,
    voice_id: str,
    api_key: str,
    output_path: str,
    stability: float = 0.7,
    similarity_boost: float = 0.8,
    style: float = 0.3,
    speed: float = 0.85,
    model_id: str = "eleven_v3",
) -> str:
    """
    ElevenLabs API로 TTS 음성을 생성한다.

    Args:
        text: 대본 텍스트
        voice_id: ElevenLabs Voice ID
        api_key: ElevenLabs API Key
        output_path: 저장할 MP3 파일 경로
        stability: 음성 안정성 (0.0 ~ 1.0)
        similarity_boost: 유사도 부스트 (0.0 ~ 1.0)
        style: 스타일 강도 (0.0 ~ 1.0)
        speed: 속도 (0.5 ~ 2.0, 기본 0.85 = 느리게)
        model_id: 사용할 모델 ID

    Returns:
        생성된 MP3 파일 경로
    """
    url = f"{ELEVENLABS_API_URL}/{voice_id}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }

    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": True,
        },
    }

    # speed는 v1 API에서 query param이 아닌 body에 포함
    if speed != 1.0:
        payload["voice_settings"]["speed"] = speed

    print(f"[TTS] 음성 생성 중... (voice_id: {voice_id})")
    print(f"[TTS] 텍스트 길이: {len(text)}자")

    response = requests.post(url, json=payload, headers=headers, timeout=120)

    if response.status_code != 200:
        raise RuntimeError(
            f"[TTS] ElevenLabs API 에러 (HTTP {response.status_code}): "
            f"{response.text[:300]}"
        )

    # 출력 디렉토리 생성
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(response.content)

    file_size = os.path.getsize(output_path)
    print(f"[TTS] ✅ 생성 완료: {output_path} ({file_size / 1024:.1f} KB)")

    return output_path


def generate_tts_from_file(
    script_path: str,
    voice_id: str,
    api_key: str,
    output_path: str,
    **kwargs,
) -> str:
    """
    스크립트 파일에서 텍스트를 읽어 TTS를 생성한다.

    Args:
        script_path: 대본 텍스트 파일 경로
        voice_id: ElevenLabs Voice ID
        api_key: ElevenLabs API Key
        output_path: 저장할 MP3 파일 경로
        **kwargs: generate_tts에 전달할 추가 파라미터

    Returns:
        생성된 MP3 파일 경로
    """
    with open(script_path, "r", encoding="utf-8") as f:
        text = f.read().strip()

    if not text:
        raise ValueError(f"[TTS] 스크립트 파일이 비어있습니다: {script_path}")

    print(f"[TTS] 스크립트 로드: {script_path}")
    return generate_tts(text, voice_id, api_key, output_path, **kwargs)
