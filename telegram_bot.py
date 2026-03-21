#!/usr/bin/env python3
"""
telegram_bot.py — 호암도사 음성 편집 봇
텔레그램에서 음성/오디오를 보내면 무음 처리 후 완성본을 회신한다.

Usage:
    python3 telegram_bot.py
"""

import os
import sys
import time
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 모듈 임포트
from silence_remover import remove_silence

# .env 로드
load_dotenv(Path(__file__).parent / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")
ALLOWED_CHAT_IDS = os.getenv("ALLOWED_CHAT_IDS", "")  # 쉼표 구분, 비어있으면 모두 허용

# 프로젝트 설정
import json
_CONFIG_PATH = Path(__file__).parent / "project.json"
if _CONFIG_PATH.exists():
    with open(_CONFIG_PATH) as f:
        _CONFIG = json.load(f)
else:
    _CONFIG = {}

SETTINGS = _CONFIG.get("settings", {})

# 기본 배속 (사용자별 설정 가능)
_user_speed = {}  # {chat_id: speed}
_user_stt_mode = {}  # {chat_id: bool}
DEFAULT_SPEED = 1.1

# 출력 디렉토리
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 봇 시작 시간
_BOT_START_TIME = datetime.now()


# ── 유틸: 사용자 제한 ──
def _is_allowed(chat_id: int) -> bool:
    """허용된 사용자인지 확인한다."""
    if not ALLOWED_CHAT_IDS:
        return True  # 비어있으면 모두 허용
    allowed = [int(x.strip()) for x in ALLOWED_CHAT_IDS.split(",") if x.strip()]
    return chat_id in allowed


# ── 유틸: 재시도 로직 ──
def retry(max_retries=3, delay=2):
    """동기 함수용 재시도 데코레이터"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait = delay * (attempt + 1)
                        print(f"[RETRY] {func.__name__} 실패 ({attempt+1}/{max_retries}), {wait}초 후 재시도: {e}")
                        time.sleep(wait)
                    else:
                        raise
        return wrapper
    return decorator


# ── 유틸: 오래된 파일 정리 ──
def cleanup_old_files(directory: Path, days: int = 7):
    """지정 일수 지난 파일을 삭제한다."""
    cutoff = datetime.now() - timedelta(days=days)
    count = 0
    for f in directory.iterdir():
        if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            count += 1
    if count:
        print(f"[CLEANUP] {count}개 파일 삭제 ({days}일 이상 경과)")


def _extract_pdf_text(pdf_path: str) -> str:
    """PDF에서 텍스트 추출"""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except ImportError:
        pass

    # fallback: pdftotext (macOS)
    import subprocess
    result = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout.strip()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 안내"""
    chat_id = update.effective_chat.id
    speed = _user_speed.get(chat_id, DEFAULT_SPEED)
    await update.message.reply_text(
        "🎙️ *호암도사 음성 편집 봇*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *기능 안내*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎤 *음성/오디오 보내기*\n"
        f"→ {speed}배속 + 무음 편집 + SRT 자막\n\n"
        "🔗 *유튜브 링크 보내기*\n"
        "→ 스크립트 + 이미지 검색어 + Pexels 이미지\n\n"
        "📝 *대본 텍스트 보내기*\n"
        "→ 문장별 이미지 검색어 생성\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📋 *명령어*\n"
        f"`/speed 1.2` — 배속 변경 (현재: {speed}x)\n"
        "`/srt` — SRT 전용 모드 전환\n"
        "`/history` — 최근 처리 파일 목록\n"
        "`/status` — 봇 상태 확인\n\n"
        f"🔑 Chat ID: `{chat_id}`",
        parse_mode="Markdown",
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """음성 메시지 또는 오디오 파일을 받아 무음 처리 후 회신"""
    if not _is_allowed(update.effective_chat.id):
        await update.message.reply_text("⛔ 권한이 없습니다.")
        return

    # SRT 전용 모드면 SRT 처리
    chat_id = update.effective_chat.id
    if _user_stt_mode.get(chat_id, False):
        await _handle_srt_mode(update, context)
        return

    # 음성메시지 or 오디오 파일 구분
    if update.message.voice:
        file = await update.message.voice.get_file()
        input_ext = ".ogg"
        duration = update.message.voice.duration
    elif update.message.audio:
        file = await update.message.audio.get_file()
        input_ext = Path(update.message.audio.file_name or "audio.mp3").suffix or ".mp3"
        duration = update.message.audio.duration
    elif update.message.document:
        doc = update.message.document
        mime = doc.mime_type or ""
        if not mime.startswith("audio/"):
            await update.message.reply_text("⚠️ 오디오 파일만 지원합니다.")
            return
        file = await doc.get_file()
        input_ext = Path(doc.file_name or "audio.mp3").suffix or ".mp3"
        duration = 0
    else:
        return

    # 처리 중 메시지
    dur_text = f" ({duration}초)" if duration else ""
    status_msg = await update.message.reply_text(f"✂️ 무음 처리 중...{dur_text}")

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        input_path = str(OUTPUT_DIR / f"tg_{timestamp}_input{input_ext}")
        output_path = str(OUTPUT_DIR / f"tg_{timestamp}_processed.mp3")

        # 파일 다운로드
        await file.download_to_drive(input_path)
        print(f"[BOT] 다운로드 완료: {input_path}")

        # OGG → MP3 변환 (텔레그램 음성메시지는 OGG)
        loop = asyncio.get_event_loop()
        if input_ext == ".ogg":
            import subprocess
            mp3_input = str(OUTPUT_DIR / f"tg_{timestamp}_input.mp3")
            await loop.run_in_executor(None, lambda: subprocess.run(
                ["ffmpeg", "-y", "-i", input_path, "-c:a", "libmp3lame", "-b:a", "192k", mp3_input],
                capture_output=True, timeout=600,
            ))
            os.remove(input_path)
            input_path = mp3_input

        # 배속 처리
        chat_id = update.effective_chat.id
        speed = _user_speed.get(chat_id, DEFAULT_SPEED)
        await status_msg.edit_text(f"⚡ {speed}배속 처리 중...")
        import subprocess
        speed_path = str(OUTPUT_DIR / f"tg_{timestamp}_speed.mp3")
        await loop.run_in_executor(None, lambda: subprocess.run(
            ["ffmpeg", "-y", "-i", input_path,
             "-filter:a", f"atempo={speed}",
             "-c:a", "libmp3lame", "-b:a", "192k", speed_path],
            capture_output=True, timeout=600,
        ))
        os.remove(input_path)
        input_path = speed_path

        # 무음 처리
        await status_msg.edit_text("✂️ 무음 편집 중...")
        result = await loop.run_in_executor(
            None,
            lambda: remove_silence(
                input_path=input_path,
                output_path=output_path,
                threshold_db=SETTINGS.get("silence_threshold", -35),
                min_duration=SETTINGS.get("silence_min_duration", 0.5),
            ),
        )

        final_path, silences = result

        # SRT 자막 생성 (배속 전 원본 기준)
        srt_path = None
        try:
            await status_msg.edit_text("📝 자막 생성 중...")
            from srt_generator import generate_srt
            srt_output = str(OUTPUT_DIR / f"tg_{timestamp}.srt")
            srt_path = await loop.run_in_executor(
                None, lambda: generate_srt(final_path, srt_output)
            )
        except Exception as e:
            print(f"[BOT] SRT 생성 실패 (스킵): {e}")

        # 결과 파일 전송
        from silence_remover import get_duration
        orig_dur = get_duration(input_path)
        new_dur = get_duration(final_path)

        caption = (
            f"✅ 처리 완료 (1.1배속 + 무음 편집)\n"
            f"⏱ {orig_dur:.1f}초 → {new_dur:.1f}초\n"
            f"✂️ 무음 {len(silences)}구간 감지"
        )
        if srt_path:
            caption += "\n📝 자막(SRT) 첨부됨"

        with open(final_path, "rb") as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                title=f"편집_{timestamp}",
                caption=caption,
            )

        # SRT 파일 전송
        if srt_path and os.path.exists(srt_path):
            with open(srt_path, "rb") as srt_file:
                await update.message.reply_document(
                    document=srt_file,
                    filename=f"호암도사_{timestamp}.srt",
                    caption="📝 캡컷용 SRT 자막 파일",
                )

        # Google Drive 업로드 (선택적)
        try:
            from drive_uploader import upload_to_drive
            await loop.run_in_executor(
                None,
                lambda: upload_to_drive(
                    file_path=final_path,
                    folder_id=GDRIVE_FOLDER_ID or None,
                    file_name=f"호암도사_{timestamp}.mp3",
                ),
            )
            await status_msg.edit_text("✅ 완료! (Drive 업로드 됨)")
        except FileNotFoundError:
            await status_msg.edit_text("✅ 완료!")
        except Exception as e:
            print(f"[BOT] Drive 업로드 실패: {e}")
            await status_msg.edit_text("✅ 완료!")

        # 입력 파일 삭제 (처리본만 유지)
        if os.path.exists(input_path):
            os.remove(input_path)

    except Exception as e:
        error_msg = f"❌ 에러: {str(e)[:200]}"
        print(f"[BOT] {error_msg}")
        await status_msg.edit_text(error_msg)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """텍스트 메시지: 유튜브 링크면 스크립트 추출, 아니면 안내"""
    import re
    text = update.message.text.strip()

    # SRT 모드면 대본으로 처리
    chat_id = update.effective_chat.id
    if _user_stt_mode.get(chat_id, False):
        await _handle_srt_mode(update, context)
        return

    # 유튜브 URL 감지
    yt_pattern = r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w\-]+"
    match = re.search(yt_pattern, text)

    if match:
        url = match.group(0)
        if not url.startswith("http"):
            url = "https://" + url
        await _handle_youtube(update, url)
    elif len(text) > 10:
        await _handle_keyword_from_text(update, text)
    else:
        await update.message.reply_text(
            "🎙️ 사용법:\n"
            "• 음성/오디오 보내기 → 배속 + 무음 편집\n"
            "• 유튜브 링크 보내기 → 스크립트 + 검색어 추출\n"
            "• 대본 텍스트 보내기 → 이미지 검색어 생성"
        )


async def _handle_keyword_from_text(update: Update, text: str):
    """텍스트(대본) → 문장별 이미지 검색어 생성"""
    import re
    status_msg = await update.message.reply_text("🔍 이미지 검색어 생성 중...")

    try:
        from keyword_generator import generate_keywords, format_keywords_text

        sentences = re.split(r"(?<=[.!?。\n])\s*", text)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 3]

        loop = asyncio.get_event_loop()
        keywords = await loop.run_in_executor(
            None, lambda: generate_keywords(sentences)
        )

        kw_text = f"🔍 이미지 검색어 ({len(sentences)}문장)\n\n{format_keywords_text(keywords)}"
        if len(kw_text) > 4000:
            for i in range(0, len(kw_text), 4000):
                await update.message.reply_text(kw_text[i:i+4000])
        else:
            await update.message.reply_text(kw_text)

        await status_msg.edit_text("✅ 완료!")

    except Exception as e:
        await status_msg.edit_text(f"❌ 에러: {str(e)[:200]}")


async def _handle_youtube(update: Update, url: str):
    """유튜브 링크 → 스크립트 추출 + 이미지 검색어 생성"""
    status_msg = await update.message.reply_text("📥 유튜브 스크립트 추출 중...")

    try:
        from script_extractor import extract_script
        from keyword_generator import generate_keywords, format_keywords_text

        loop = asyncio.get_event_loop()

        # 스크립트 추출
        result = await loop.run_in_executor(
            None, lambda: extract_script(url)
        )

        title = result["title"]
        script = result["script"]
        sentences = result["sentences"]

        # 스크립트 전송 (길면 분할)
        script_text = f"📝 **{title}**\n\n{script}"
        if len(script_text) > 4000:
            # 4000자씩 분할
            for i in range(0, len(script_text), 4000):
                await update.message.reply_text(
                    script_text[i:i+4000],
                    parse_mode="Markdown",
                )
        else:
            await update.message.reply_text(script_text, parse_mode="Markdown")

        # 이미지 검색어 생성
        await status_msg.edit_text("🔍 이미지 검색어 생성 중...")

        keywords = await loop.run_in_executor(
            None, lambda: generate_keywords(sentences)
        )

        kw_text = f"🔍 **이미지 검색어**\n\n{format_keywords_text(keywords)}"
        if len(kw_text) > 4000:
            for i in range(0, len(kw_text), 4000):
                await update.message.reply_text(kw_text[i:i+4000])
        else:
            await update.message.reply_text(kw_text)

        await status_msg.edit_text(
            f"✅ 완료! ({len(sentences)}문장, {result['method']})"
        )

    except Exception as e:
        error_msg = f"❌ 에러: {str(e)[:300]}"
        print(f"[BOT] {error_msg}")
        await status_msg.edit_text(error_msg)


async def keyword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/keyword 명령어: 텍스트 → 이미지 검색어 생성"""
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "사용법: /keyword 스크립트 텍스트를 입력하세요"
        )
        return

    status_msg = await update.message.reply_text("🔍 이미지 검색어 생성 중...")

    try:
        from keyword_generator import generate_keywords, format_keywords_text
        import re

        sentences = re.split(r"(?<=[.!?。])\s+", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        loop = asyncio.get_event_loop()
        keywords = await loop.run_in_executor(
            None, lambda: generate_keywords(sentences)
        )

        kw_text = f"🔍 **이미지 검색어**\n\n{format_keywords_text(keywords)}"
        await update.message.reply_text(kw_text)
        await status_msg.edit_text("✅ 완료!")

    except Exception as e:
        await status_msg.edit_text(f"❌ 에러: {str(e)[:200]}")


async def speed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/speed 명령어: 배속 변경"""
    if not _is_allowed(update.effective_chat.id):
        return
    chat_id = update.effective_chat.id
    if context.args:
        try:
            speed = float(context.args[0])
            if 0.5 <= speed <= 3.0:
                _user_speed[chat_id] = speed
                await update.message.reply_text(f"⚡ 배속 변경: {speed}x")
            else:
                await update.message.reply_text("⚠️ 0.5 ~ 3.0 사이로 입력하세요")
        except ValueError:
            await update.message.reply_text("⚠️ 숫자를 입력하세요 (예: /speed 1.2)")
    else:
        current = _user_speed.get(chat_id, DEFAULT_SPEED)
        await update.message.reply_text(
            f"현재 배속: {current}x\n"
            "변경: /speed 1.2"
        )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/history 명령어: 최근 처리 파일 목록"""
    if not _is_allowed(update.effective_chat.id):
        return
    files = sorted(OUTPUT_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    files = [f for f in files if f.is_file() and f.suffix in (".mp3", ".srt")]

    if not files:
        await update.message.reply_text("📂 처리된 파일이 없습니다.")
        return

    lines = ["📂 *최근 파일* (최대 15개)\n"]
    for f in files[:15]:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        size_kb = f.stat().st_size / 1024
        lines.append(f"`{f.name}` ({size_kb:.0f}KB) {mtime:%m/%d %H:%M}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status 명령어: 봇 상태 확인"""
    if not _is_allowed(update.effective_chat.id):
        return
    uptime = datetime.now() - _BOT_START_TIME
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)

    files = [f for f in OUTPUT_DIR.iterdir() if f.is_file()]
    total_size = sum(f.stat().st_size for f in files) / 1024 / 1024
    chat_id = update.effective_chat.id
    speed = _user_speed.get(chat_id, DEFAULT_SPEED)

    import shutil
    disk = shutil.disk_usage(str(OUTPUT_DIR))
    disk_free = disk.free / 1024 / 1024 / 1024

    await update.message.reply_text(
        "📊 *봇 상태*\n\n"
        f"⏱ 업타임: {hours}시간 {minutes}분\n"
        f"📂 파일 수: {len(files)}개 ({total_size:.1f}MB)\n"
        f"💾 디스크 여유: {disk_free:.1f}GB\n"
        f"⚡ 현재 배속: {speed}x\n"
        f"🔑 Chat ID: `{chat_id}`",
        parse_mode="Markdown",
    )


async def srt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/srt 명령어: SRT 전용 모드 토글"""
    if not _is_allowed(update.effective_chat.id):
        return
    chat_id = update.effective_chat.id
    current = _user_stt_mode.get(chat_id, False)
    _user_stt_mode[chat_id] = not current
    if not current:
        await update.message.reply_text(
            "📝 *SRT 모드 ON*\n"
            "음성 보내면 → SRT 자막만 회신\n"
            "(배속/무음 처리 없음)\n\n"
            "해제: /srt",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("🎤 *일반 모드 복귀* (배속 + 무음 + SRT)", parse_mode="Markdown")


async def _handle_srt_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SRT 전용: 음성 → SRT만 회신"""
    if update.message.text:
        return  # 텍스트 무시

    if update.message.voice:
        file = await update.message.voice.get_file()
        input_ext = ".ogg"
    elif update.message.audio:
        file = await update.message.audio.get_file()
        input_ext = Path(update.message.audio.file_name or "audio.mp3").suffix or ".mp3"
    elif update.message.document:
        file = await update.message.document.get_file()
        input_ext = Path(update.message.document.file_name or "audio.mp3").suffix or ".mp3"
    else:
        return

    status_msg = await update.message.reply_text("📝 자막 생성 중...")

    try:
        import subprocess
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        input_path = str(OUTPUT_DIR / f"srt_{timestamp}_input{input_ext}")
        await file.download_to_drive(input_path)

        loop = asyncio.get_event_loop()

        # OGG → MP3
        if input_ext == ".ogg":
            mp3_path = str(OUTPUT_DIR / f"srt_{timestamp}_input.mp3")
            await loop.run_in_executor(None, lambda: subprocess.run(
                ["ffmpeg", "-y", "-i", input_path, "-c:a", "libmp3lame", "-b:a", "192k", mp3_path],
                capture_output=True, timeout=600,
            ))
            os.remove(input_path)
            input_path = mp3_path

        # SRT 생성
        from srt_generator import generate_srt
        srt_path = str(OUTPUT_DIR / f"srt_{timestamp}.srt")
        srt_path = await loop.run_in_executor(
            None, lambda: generate_srt(input_path, srt_path)
        )

        # SRT 회신
        with open(srt_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"자막_{timestamp}.srt",
                caption="📝 SRT 자막",
            )

        await status_msg.edit_text("✅ 자막 생성 완료!")

        if os.path.exists(input_path):
            os.remove(input_path)

    except Exception as e:
        await status_msg.edit_text(f"❌ 에러: {str(e)[:200]}")


async def srt_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/srt_now: 대본 없이 저장된 오디오로 Whisper SRT 생성"""
    if not _is_allowed(update.effective_chat.id):
        return
    audio_path = context.user_data.get("srt_audio_path")
    if not audio_path or not os.path.exists(audio_path):
        await update.message.reply_text("⚠️ 저장된 오디오가 없습니다. 먼저 음성을 보내주세요.")
        return

    status_msg = await update.message.reply_text("📝 Whisper 자막 생성 중...")

    try:
        from srt_generator import generate_srt
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        srt_path = str(OUTPUT_DIR / f"srt_{timestamp}.srt")

        loop = asyncio.get_event_loop()
        srt_path = await loop.run_in_executor(
            None, lambda: generate_srt(audio_path, srt_path)
        )

        with open(srt_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"자막_{timestamp}.srt",
                caption="📝 SRT 자막 (Whisper)",
            )

        await status_msg.edit_text("✅ 자막 생성 완료!")

        context.user_data.pop("srt_audio_path", None)
        if os.path.exists(audio_path):
            os.remove(audio_path)

    except Exception as e:
        await status_msg.edit_text(f"❌ 에러: {str(e)[:200]}")


def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        print("❌ TELEGRAM_BOT_TOKEN이 설정되지 않았습니다!")
        sys.exit(1)

    print("=" * 50)
    print("🤖 호암도사 음성 편집 봇 시작")
    print(f"   무음 임계값: {SETTINGS.get('silence_threshold', -35)}dB")
    print(f"   최소 무음 길이: {SETTINGS.get('silence_min_duration', 0.5)}s")
    print(f"   Drive 폴더: {GDRIVE_FOLDER_ID or '없음'}")
    print(f"   허용 사용자: {ALLOWED_CHAT_IDS or '모두'}")
    print("=" * 50)

    # 시작 시 오래된 파일 정리
    cleanup_old_files(OUTPUT_DIR, days=7)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("speed", speed_command))
    app.add_handler(CommandHandler("srt", srt_command))
    app.add_handler(CommandHandler("srt_now", srt_now_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("keyword", keyword_command))
    # 음성 메시지, 오디오 파일, 문서(오디오/PDF) 처리
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.Document.ALL, handle_voice))
    # 텍스트: 유튜브 링크 감지 또는 대본 처리
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("[BOT] 봇 실행 중... (Ctrl+C로 종료)")
    app.run_polling()


if __name__ == "__main__":
    main()
