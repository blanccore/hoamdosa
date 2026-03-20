"""
drive_uploader.py — Google Drive 업로드 모듈
OAuth2 인증으로 Google Drive에 파일을 업로드한다.
"""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# 프로젝트 디렉토리 기준 경로
_BASE_DIR = Path(__file__).parent
_TOKEN_PATH = _BASE_DIR / "token.json"
_CREDENTIALS_PATH = _BASE_DIR / "credentials.json"


def _get_credentials() -> Credentials:
    """
    OAuth2 인증을 수행하고 자격증명을 반환한다.
    최초 실행 시 브라우저 인증, 이후 token.json으로 자동 갱신.
    """
    creds = None

    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"[DRIVE] credentials.json 없음: {_CREDENTIALS_PATH}\n"
                    "Google Cloud Console에서 OAuth 2.0 자격증명을 다운로드하세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 토큰 저장
        with open(_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print(f"[DRIVE] 토큰 저장: {_TOKEN_PATH}")

    return creds


def upload_to_drive(
    file_path: str,
    folder_id: str = None,
    file_name: str = None,
) -> dict:
    """
    파일을 Google Drive에 업로드한다.

    Args:
        file_path: 업로드할 파일 경로
        folder_id: 업로드할 Drive 폴더 ID (없으면 루트)
        file_name: Drive에서 사용할 파일명 (없으면 원본 파일명)

    Returns:
        {"id": str, "name": str, "webViewLink": str}
    """
    creds = _get_credentials()
    service = build("drive", "v3", credentials=creds)

    if not file_name:
        file_name = Path(file_path).name

    # MIME 타입 추정
    ext = Path(file_path).suffix.lower()
    mime_map = {
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".txt": "text/plain",
        ".json": "application/json",
    }
    mime_type = mime_map.get(ext, "application/octet-stream")

    # 파일 메타데이터
    file_metadata = {"name": file_name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)

    print(f"[DRIVE] 업로드 중: {file_name} ({mime_type})")

    file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id,name,webViewLink")
        .execute()
    )

    print(f"[DRIVE] ✅ 업로드 완료: {file.get('name')}")
    print(f"[DRIVE] 링크: {file.get('webViewLink', 'N/A')}")

    return file


def ensure_drive_auth():
    """Drive 인증을 미리 수행한다 (최초 설정용)."""
    try:
        creds = _get_credentials()
        service = build("drive", "v3", credentials=creds)
        about = service.about().get(fields="user").execute()
        user = about.get("user", {})
        print(f"[DRIVE] ✅ 인증 성공: {user.get('displayName', 'Unknown')} ({user.get('emailAddress', '')})")
        return True
    except Exception as e:
        print(f"[DRIVE] ❌ 인증 실패: {e}")
        return False


if __name__ == "__main__":
    ensure_drive_auth()
