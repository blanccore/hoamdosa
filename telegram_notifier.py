"""
telegram_notifier.py — 텔레그램 알림 모듈
웹 서버에서 처리된 결과를 텔레그램으로 자동 전송한다.
"""

import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "")


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def send_message(text: str, chat_id: str = None):
    """텔레그램으로 텍스트 메시지 전송"""
    cid = chat_id or NOTIFY_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not cid:
        return
    requests.post(_api_url("sendMessage"), data={
        "chat_id": cid,
        "text": text,
        "parse_mode": "Markdown",
    }, timeout=10)


def send_audio(filepath: str, caption: str = "", chat_id: str = None):
    """텔레그램으로 오디오 파일 전송"""
    cid = chat_id or NOTIFY_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not cid:
        return
    with open(filepath, "rb") as f:
        requests.post(_api_url("sendAudio"), data={
            "chat_id": cid,
            "caption": caption,
        }, files={"audio": (Path(filepath).name, f, "audio/mpeg")}, timeout=60)


def send_document(filepath: str, caption: str = "", chat_id: str = None):
    """텔레그램으로 문서 파일 전송"""
    cid = chat_id or NOTIFY_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not cid:
        return
    with open(filepath, "rb") as f:
        requests.post(_api_url("sendDocument"), data={
            "chat_id": cid,
            "caption": caption,
        }, files={"document": (Path(filepath).name, f)}, timeout=60)


def send_photo(filepath: str, caption: str = "", chat_id: str = None):
    """텔레그램으로 이미지 전송"""
    cid = chat_id or NOTIFY_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not cid:
        return
    with open(filepath, "rb") as f:
        requests.post(_api_url("sendPhoto"), data={
            "chat_id": cid,
            "caption": caption,
        }, files={"photo": (Path(filepath).name, f)}, timeout=30)


def notify_audio_result(audio_path: str, srt_path: str = None, info: dict = None):
    """음성 처리 결과를 텔레그램으로 전송"""
    caption = "✅ 웹 대시보드 처리 완료"
    if info:
        caption += f"\n⏱ {info.get('duration', 0)}초"
        caption += f"\n⚡ {info.get('speed', 1.1)}x"
        caption += f"\n✂️ 무음 {info.get('silences_count', 0)}구간"

    send_audio(audio_path, caption)
    if srt_path and os.path.exists(srt_path):
        send_document(srt_path, "📝 SRT 자막")


def notify_keywords(text: str):
    """검색어 결과를 텔레그램으로 전송"""
    send_message(text)
