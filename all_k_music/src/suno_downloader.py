"""
Suno Downloader — All k Music
────────────────────────────────────────────────────────────────────────
Suno AI 非公式セッション API を使った楽曲生成・ポーリング・ダウンロード。

認証フロー:
  ① config/suno_config.json の __client Cookie → Clerk JWT 取得
  ② JWT を Bearer トークンとして Suno Studio API を呼び出す
  ③ 生成完了後に MP3 + ジャケット画像をローカルに保存

Cookie 未設定 / API エラー時は DEMO MODE にフォールバックし、
プレースホルダーファイルを生成してシステムをクラッシュさせない。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from src.asset_vault import stamp_entry, append_vault

logger = logging.getLogger(__name__)

# ── API エンドポイント ─────────────────────────────────────────────────────
CLERK_BASE = "https://clerk.suno.ai"
SUNO_BASE  = "https://studio-api.suno.ai"

# Suno が受け付けるステータス値
_STATUS_COMPLETE = "complete"
_STATUS_ERROR    = "error"
_STATUS_FINAL    = {_STATUS_COMPLETE, _STATUS_ERROR}


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
class SunoConfig:
    """
    config/suno_config.json を読み込む。
    ファイルが存在しない場合はデフォルトを自動生成する。
    """

    _DEFAULTS = {
        "_readme": "Set cookie to your __client cookie from suno.ai to enable real generation.",
        "cookie": "",
        "model_version": "chirp-v3-5",
        "max_retries": 5,
        "poll_interval_seconds": 8,
        "poll_timeout_seconds": 360,
    }

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._DEFAULTS, indent=2), encoding="utf-8")
            logger.warning("[Config] Created default config at %s", path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._d: Dict = {**self._DEFAULTS, **raw}

    @property
    def cookie(self) -> str:
        # 環境変数 SUNO_COOKIE を優先 (GitHub Actions Secrets 連携用)
        env_cookie = os.environ.get("SUNO_COOKIE", "").strip()
        if env_cookie:
            return env_cookie
        return str(self._d.get("cookie", "")).strip()

    @property
    def model_version(self) -> str:
        return str(self._d.get("model_version", "chirp-v3-5"))

    @property
    def max_retries(self) -> int:
        return int(self._d.get("max_retries", 5))

    @property
    def poll_interval(self) -> int:
        return int(self._d.get("poll_interval_seconds", 8))

    @property
    def poll_timeout(self) -> int:
        return int(self._d.get("poll_timeout_seconds", 360))

    @property
    def is_demo(self) -> bool:
        return not bool(self.cookie)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _extract_session_id(cookie: str) -> str:
    """
    __client Cookie の JWT ペイロードから lastActiveSessionId を取得する。
    Cookie 文字列の形式: "__client=<JWT>" または "__client=<URL_encoded_JWT>"
    """
    for segment in cookie.split(";"):
        segment = segment.strip()
        if not segment.startswith("__client="):
            continue
        jwt_raw = urllib.parse.unquote(segment[len("__client="):])
        parts = jwt_raw.split(".")
        if len(parts) < 2:
            continue
        # Base64 パディングを補完してデコード
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        try:
            payload = json.loads(base64.b64decode(payload_b64))
            sid = payload.get("lastActiveSessionId", "")
            if sid:
                return sid
        except Exception as exc:
            logger.debug("JWT decode failed: %s", exc)
    raise ValueError(
        "__client cookie から session ID を抽出できませんでした。"
        "Cookie の形式が '__client=<JWT>' になっているか確認してください。"
    )


def _make_asset_id(global_index: int) -> str:
    """例: 20260516-003"""
    return f"{datetime.now().strftime('%Y%m%d')}-{global_index:03d}"


# ─────────────────────────────────────────────────────────────────────────────
# Downloader
# ─────────────────────────────────────────────────────────────────────────────
class SunoDownloader:
    """
    Suno AI からの楽曲生成・ダウンロードを担う中核クラス。

    DEMO MODE (cookie 未設定):
        実際の API 呼び出しは行わず、プレースホルダーファイルを生成して
        ログを蓄積できる状態にする。

    LIVE MODE (cookie 設定済み):
        Clerk JWT → Suno API でリクエスト → ポーリング → MP3/画像ダウンロード
    """

    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://suno.ai/",
        "Origin":  "https://suno.ai",
    }

    def __init__(
        self,
        config: SunoConfig,
        tracks_dir: Path,
        covers_dir: Path,
        vault_path: Optional[Path] = None,
    ) -> None:
        self.cfg = config
        self.tracks_dir = tracks_dir
        self.covers_dir = covers_dir
        self.vault_path = vault_path  # 証拠台帳 JSONL パス (None = 無効)
        tracks_dir.mkdir(parents=True, exist_ok=True)
        covers_dir.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._session.headers.update(self._BROWSER_HEADERS)
        self._jwt: str = ""

    # ── 認証 ────────────────────────────────────────────────────────────

    def _refresh_jwt(self) -> bool:
        """Clerk から JWT を取得して session ヘッダーにセットする。"""
        try:
            session_id = _extract_session_id(self.cfg.cookie)
        except ValueError as exc:
            logger.error("[Auth] %s", exc)
            return False

        url = f"{CLERK_BASE}/v1/client/sessions/{session_id}/tokens"
        try:
            resp = self._session.post(
                url,
                headers={"Cookie": self.cfg.cookie},
                timeout=20,
            )
            resp.raise_for_status()
            self._jwt = resp.json().get("jwt", "")
            if not self._jwt:
                logger.error("[Auth] Clerk から空の JWT が返りました。")
                return False
            self._session.headers["Authorization"] = f"Bearer {self._jwt}"
            logger.info("[Auth] JWT を更新しました (session=%s…)", session_id[:8])
            return True
        except Exception as exc:
            logger.error("[Auth] JWT 取得失敗: %s", exc)
            return False

    def _auth_with_retry(self) -> bool:
        for attempt in range(self.cfg.max_retries):
            if self._refresh_jwt():
                return True
            if attempt < self.cfg.max_retries - 1:
                wait = min(10 * (2 ** attempt), 120)
                logger.warning("[Auth] リトライ %d/%d — %ds 後…", attempt + 1, self.cfg.max_retries, wait)
                time.sleep(wait)
        return False

    # ── 生成リクエスト ───────────────────────────────────────────────────

    def _post_generate(self, prompt: dict) -> List[str]:
        """
        Suno v2 API に生成リクエストを送信し、clip ID リストを返す。
        """
        # 安全ロック: continue_clip_id / remix 系は絶対に None/False で送信
        payload = {
            "prompt":            "",
            "generation_type":   "TEXT",
            "tags":              prompt["style_prompt"],
            "negative_tags":     prompt.get("negative_prompt", ""),
            "mv":                self.cfg.model_version,
            "title":             f"{prompt['genre_name']} — All k Music",
            "make_instrumental": True,   # 常に True (ボーカル入り生成禁止)
            "continue_clip_id":  None,   # 常に None (他者楽曲への継続禁止)
            "continue_at":       None,
        }
        try:
            resp = self._session.post(
                f"{SUNO_BASE}/api/generate/v2/",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data  = resp.json()
            clips = data.get("clips", [])
            ids   = [c["id"] for c in clips if "id" in c]
            logger.info("[Generate] 送信完了 — clip IDs: %s", ids)
            return ids
        except Exception as exc:
            logger.error("[Generate] リクエスト失敗: %s", exc)
            return []

    def _generate_with_retry(self, prompt: dict) -> List[str]:
        for attempt in range(self.cfg.max_retries):
            ids = self._post_generate(prompt)
            if ids:
                return ids
            if attempt < self.cfg.max_retries - 1:
                wait = min(8 * (2 ** attempt), 60)
                logger.warning("[Generate] リトライ %d/%d — %ds 後…", attempt + 1, self.cfg.max_retries, wait)
                time.sleep(wait)
        return []

    # ── ポーリング ───────────────────────────────────────────────────────

    def _poll_until_complete(self, clip_ids: List[str]) -> List[dict]:
        """
        clips が 'complete' になるまで定期ポーリングする。
        タイムアウトした場合は空リストを返す。
        """
        ids_str  = ",".join(clip_ids)
        deadline = time.monotonic() + self.cfg.poll_timeout
        elapsed  = 0

        while time.monotonic() < deadline:
            try:
                resp = self._session.get(
                    f"{SUNO_BASE}/api/feed/",
                    params={"ids": ids_str},
                    timeout=20,
                )
                resp.raise_for_status()
                raw = resp.json()
                # API によってレスポンスがリストまたは {"clips": [...]}
                clips: List[dict] = raw if isinstance(raw, list) else raw.get("clips", [])

                done    = [c for c in clips if c.get("status") == _STATUS_COMPLETE]
                errored = [c for c in clips if c.get("status") == _STATUS_ERROR]
                pending = [c for c in clips if c.get("status") not in _STATUS_FINAL]

                for e in errored:
                    logger.warning("[Poll] Clip %s がエラー: %s", e.get("id"), e.get("error_message"))

                logger.info(
                    "[Poll] elapsed=%ds  complete=%d  pending=%d  error=%d",
                    elapsed, len(done), len(pending), len(errored),
                )

                if not pending:
                    return done

            except Exception as exc:
                logger.warning("[Poll] リクエスト失敗: %s — リトライ中…", exc)

            time.sleep(self.cfg.poll_interval)
            elapsed += self.cfg.poll_interval

        logger.error("[Poll] タイムアウト (%ds) — complete clip なし", self.cfg.poll_timeout)
        return []

    # ── ダウンロード ─────────────────────────────────────────────────────

    def _download_binary(self, url: str, dest: Path) -> bool:
        """URL をバイナリ取得してローカルに保存する。"""
        try:
            resp = self._session.get(url, stream=True, timeout=120)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            logger.info("[Download] %s (%d KB)", dest.name, len(resp.content) // 1024)
            return True
        except Exception as exc:
            logger.error("[Download] 失敗 %s: %s", url, exc)
            return False

    # ── DEMO モード ──────────────────────────────────────────────────────

    def _create_demo_result(self, prompt: dict, asset_id: str) -> dict:
        """Cookie 未設定時のプレースホルダーを生成する。"""
        slug      = prompt["genre_slug"]
        mp3_path  = self.tracks_dir  / f"{asset_id}_{slug}_DEMO.mp3.placeholder"
        cover_path = self.covers_dir / f"{asset_id}_{slug}_DEMO.jpg.placeholder"

        mp3_path.write_text(
            f"[DEMO MODE] ジャンル: {prompt['genre_name']}\n"
            f"プロンプト: {prompt['style_prompt']}\n"
            "config/suno_config.json に Suno Cookie を設定すると実際の音楽が生成されます。",
            encoding="utf-8",
        )
        cover_path.write_text(
            f"[DEMO MODE] カバー画像プレースホルダー: {prompt['genre_name']}",
            encoding="utf-8",
        )
        logger.warning("[DEMO] プレースホルダーを生成: %s", asset_id)
        result = {
            "asset_id":          asset_id,
            "suno_clip_id":      f"demo-{asset_id}",
            "title":             f"[DEMO] {prompt['genre_name']}",
            "genre_slug":        prompt.get("genre_slug", ""),
            "genre":             prompt.get("genre_name", ""),
            "mp3_path":          str(mp3_path),
            "cover_path":        str(cover_path),
            "audio_url":         "",
            "status":            "demo",
            "style_prompt":      prompt.get("style_prompt", ""),
            "generation_seed":   prompt.get("generation_seed", 0),
        }
        # 証拠台帳に記録 (DEMOモードでも生成意図を残す)
        if self.vault_path:
            stamped = stamp_entry(result, result["generation_seed"], result["style_prompt"])
            append_vault(stamped, self.vault_path)
        return result

    # ── パブリック API ────────────────────────────────────────────────────

    def generate_and_download(self, prompt: dict, global_index: int) -> Optional[dict]:
        """
        1 ジャンル分のフルパイプラインを実行する。
          認証 → 生成 → ポーリング → ダウンロード → メタデータ返却

        DEMO MODE または不回復エラー時はプレースホルダーを返す。
        None を返した場合はこのジャンルをスキップする（上位でログ記録）。
        """
        asset_id = _make_asset_id(global_index)
        genre    = prompt["genre_name"]
        slug     = prompt["genre_slug"]

        # ── DEMO MODE ──────────────────────────────────────────────────
        if self.cfg.is_demo:
            logger.warning("[DEMO MODE] Cookie 未設定 → プレースホルダーを生成: %s", genre)
            return self._create_demo_result(prompt, asset_id)

        # ── 認証 ───────────────────────────────────────────────────────
        logger.info("[Pipeline] ① 認証: %s", genre)
        if not self._auth_with_retry():
            logger.error("[Pipeline] 認証失敗 — DEMO にフォールバック: %s", genre)
            return self._create_demo_result(prompt, asset_id)

        # ── 生成リクエスト ──────────────────────────────────────────────
        logger.info("[Pipeline] ② 生成リクエスト: %s", genre)
        clip_ids = self._generate_with_retry(prompt)
        if not clip_ids:
            logger.error("[Pipeline] 生成失敗 — DEMO にフォールバック: %s", genre)
            return self._create_demo_result(prompt, asset_id)

        # ── ポーリング ──────────────────────────────────────────────────
        logger.info("[Pipeline] ③ ポーリング中 … (最大 %ds)", self.cfg.poll_timeout)
        completed = self._poll_until_complete(clip_ids)
        if not completed:
            logger.error("[Pipeline] ポーリングタイムアウト — DEMO にフォールバック: %s", genre)
            return self._create_demo_result(prompt, asset_id)

        clip      = completed[0]
        audio_url = clip.get("audio_url", "")
        image_url = clip.get("image_large_url") or clip.get("image_url", "")
        title     = clip.get("title") or f"{genre} — All k Music"

        # ── ダウンロード ────────────────────────────────────────────────
        logger.info("[Pipeline] ④ ダウンロード: %s", genre)
        mp3_path   = self.tracks_dir / f"{asset_id}_{slug}.mp3"
        cover_path = self.covers_dir / f"{asset_id}_{slug}.jpg"

        mp3_ok   = bool(audio_url) and self._download_binary(audio_url, mp3_path)
        cover_ok = bool(image_url) and self._download_binary(image_url, cover_path)

        if not mp3_ok:
            logger.warning("[Pipeline] MP3 ダウンロード失敗 — DEMO にフォールバック: %s", genre)
            return self._create_demo_result(prompt, asset_id)

        result = {
            "asset_id":        asset_id,
            "suno_clip_id":    clip.get("id", ""),
            "title":           title,
            "genre_slug":      slug,
            "genre":           genre,
            "mp3_path":        str(mp3_path),
            "cover_path":      str(cover_path) if cover_ok else "",
            "audio_url":       audio_url,
            "status":          "downloaded",
            "style_prompt":    prompt.get("style_prompt", ""),
            "generation_seed": prompt.get("generation_seed", 0),
        }
        # 証拠台帳に永久保存 (ダウンロード成功時)
        if self.vault_path:
            stamped = stamp_entry(result, result["generation_seed"], result["style_prompt"])
            append_vault(stamped, self.vault_path)
            logger.info("[Vault] ✓ 証拠台帳に記録: %s  fp=%s",
                        asset_id, stamped.get("prompt_fingerprint"))
        return result
