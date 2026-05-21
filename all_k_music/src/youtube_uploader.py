"""
YouTube Uploader — All k Music
────────────────────────────────────────────────────────────────────────
YouTube Data API v3 で動画をアップロードし、サムネイルを設定する。

必要な環境変数 (GitHub Secrets):
  YOUTUBE_CLIENT_ID      — OAuth2 クライアントID
  YOUTUBE_CLIENT_SECRET  — OAuth2 クライアントシークレット
  YOUTUBE_REFRESH_TOKEN  — OAuth2 リフレッシュトークン

依存ライブラリ:
  pip install google-api-python-client google-auth
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

YOUTUBE_CATEGORY_MUSIC = "10"


def _build_service():
    """OAuth2 リフレッシュトークンから YouTube API クライアントを構築する。"""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        logger.error(
            "[YouTube] google-api-python-client / google-auth が未インストール。"
            "pip install google-api-python-client google-auth を実行してください。"
        )
        return None

    client_id     = os.environ.get("YOUTUBE_CLIENT_ID", "")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        logger.error(
            "[YouTube] 認証情報が未設定です。"
            "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN "
            "を環境変数または GitHub Secrets に登録してください。"
        )
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def parse_seo_txt(seo_path: Path) -> dict:
    """
    save_seo_txt() が出力した txt ファイルを解析して dict を返す。

    Returns:
        {"title_jp": str, "title_en": str, "description": str, "hashtags": list[str]}
    """
    lines = seo_path.read_text(encoding="utf-8").splitlines()
    result: dict = {"title_jp": "", "title_en": "", "description": "", "hashtags": []}

    mode = None
    desc_lines: list = []

    for line in lines:
        if line.startswith("TITLE (JP):"):
            result["title_jp"] = line[len("TITLE (JP):"):].strip()
        elif line.startswith("TITLE (EN):"):
            result["title_en"] = line[len("TITLE (EN):"):].strip()
        elif line.strip() == "DESCRIPTION:":
            mode = "description"
        elif line.strip() == "HASHTAGS:":
            mode = "hashtags"
            result["description"] = "\n".join(desc_lines).strip()
            desc_lines = []
        elif mode == "description":
            desc_lines.append(line)
        elif mode == "hashtags" and line.strip():
            result["hashtags"] = line.strip().split()

    if not result["description"] and desc_lines:
        result["description"] = "\n".join(desc_lines).strip()

    return result


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list,
    thumbnail_path: Optional[Path] = None,
    privacy: str = "unlisted",
    is_shorts: bool = False,
) -> Optional[str]:
    """
    動画を YouTube にアップロードして動画 URL を返す。

    Args:
        video_path:      アップロードする MP4 ファイル
        title:           動画タイトル (100文字以内)
        description:     概要欄テキスト
        tags:            タグリスト
        thumbnail_path:  サムネイル画像 (JPG/PNG)
        privacy:         "public" | "unlisted" | "private"
        is_shorts:       True の場合タイトルに #Shorts を付与

    Returns:
        動画 URL (例: https://www.youtube.com/watch?v=XXXXXXXXXXX)
        失敗時は None
    """
    svc = _build_service()
    if svc is None:
        return None

    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        logger.error("[YouTube] googleapiclient.http が import できません")
        return None

    # Shorts は #Shorts タグをタイトルに付与
    if is_shorts and "#Shorts" not in title:
        title = title + " #Shorts"

    body = {
        "snippet": {
            "title":           title[:100],
            "description":     description[:5000],
            "tags":            [t.lstrip("#") for t in tags][:500],
            "categoryId":      YOUTUBE_CATEGORY_MUSIC,
            "defaultLanguage": "ja",
        },
        "status": {
            "privacyStatus":          privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB チャンク
    )

    logger.info("[YouTube] アップロード開始: %s  (%s)", video_path.name, privacy)

    try:
        request  = svc.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            prog, response = request.next_chunk()
            if prog:
                logger.info("[YouTube]   進捗: %d%%", int(prog.progress() * 100))

        video_id = response["id"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info("[YouTube] ✓ アップロード完了: %s", url)

        # カスタムサムネイル設定
        if thumbnail_path and thumbnail_path.exists():
            try:
                thumb_media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
                svc.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
                logger.info("[YouTube] ✓ サムネイル設定完了")
            except Exception as e:
                logger.warning("[YouTube] サムネイル設定失敗: %s", e)

        return url

    except Exception as exc:
        logger.error("[YouTube] アップロード失敗: %s", exc)
        return None
