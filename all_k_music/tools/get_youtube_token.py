#!/usr/bin/env python3
"""
YouTube OAuth2 リフレッシュトークン取得ツール
─────────────────────────────────────────────────────────────────────
Phase 4 (YouTube アップロード) に必要なリフレッシュトークンを取得する。
このスクリプトはローカルで一度だけ実行する。

事前準備:
  1. https://console.cloud.google.com/ でプロジェクトを作成
  2. 「YouTube Data API v3」を有効化
  3. 「認証情報」→「OAuth 2.0 クライアント ID」→「デスクトップアプリ」で作成
  4. クライアントID とシークレットをコピーしておく

実行:
  pip install google-auth-oauthlib
  python tools/get_youtube_token.py

出力された3つの値を GitHub Secrets に登録:
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN
"""

import sys


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("インストール: pip install google-auth-oauthlib")
        sys.exit(1)

    print("=" * 60)
    print("  YouTube OAuth2 リフレッシュトークン取得")
    print("=" * 60)
    print()
    print("Google Cloud Console で取得した OAuth2 認証情報を入力してください。")
    print()

    client_id     = input("YOUTUBE_CLIENT_ID を入力     : ").strip()
    client_secret = input("YOUTUBE_CLIENT_SECRET を入力 : ").strip()

    if not client_id or not client_secret:
        print("エラー: クライアントID とシークレットは必須です。")
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id":     client_id,
            "client_secret": client_secret,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
    ]

    print()
    print("ブラウザが開きます。Google アカウントでログインして権限を許可してください。")
    print()

    flow  = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    print()
    print("=" * 60)
    print("  ✓ 認証成功！以下を GitHub Secrets に登録してください")
    print("=" * 60)
    print()
    print(f"  Secret名: YOUTUBE_CLIENT_ID")
    print(f"  値      : {client_id}")
    print()
    print(f"  Secret名: YOUTUBE_CLIENT_SECRET")
    print(f"  値      : {client_secret}")
    print()
    print(f"  Secret名: YOUTUBE_REFRESH_TOKEN")
    print(f"  値      : {creds.refresh_token}")
    print()
    print("登録先: GitHub リポジトリ → Settings → Secrets and variables → Actions")
    print("=" * 60)


if __name__ == "__main__":
    main()
