#!/usr/bin/env python3
"""
All k Music — メイン実行スクリプト
════════════════════════════════════════════════════════════════════════════
実行するとトレンドキュレーター → Suno AI 生成 → 資産ログ蓄積の
フルパイプラインが走る。

使用方法:
  cd all_k_music
  python main.py

  # 特定ジャンルのみ:
  python main.py --genre lofi
  python main.py --genre edm
  python main.py --genre ambient
  python main.py --genre synthwave
════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── パス解決（どのディレクトリからでも動作する）─────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.trend_curator import TrendCurator
from src.suno_downloader import SunoConfig, SunoDownloader

# ── ロギング設定 ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── パス定数 ─────────────────────────────────────────────────────────────
CONFIG_PATH = ROOT / "config" / "suno_config.json"
TRACKS_DIR  = ROOT / "assets" / "tracks"
COVERS_DIR  = ROOT / "assets" / "covers"
ASSET_LOG   = ROOT / "logs" / "music_assets.json"


# ─────────────────────────────────────────────────────────────────────────────
# 資産ログ管理
# ─────────────────────────────────────────────────────────────────────────────
def load_asset_log() -> list:
    if ASSET_LOG.exists():
        try:
            return json.loads(ASSET_LOG.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[Log] 読み込み失敗 (%s) — 空リストで開始", exc)
    return []


def save_asset_log(entries: list) -> None:
    ASSET_LOG.parent.mkdir(parents=True, exist_ok=True)
    ASSET_LOG.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[Log] %s に %d 件保存完了", ASSET_LOG, len(entries))


def build_log_entry(prompt: dict, result: dict) -> dict:
    """ダウンロード結果と企画情報を合体させてログエントリを生成する。"""
    return {
        "asset_id":       result["asset_id"],
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "genre":          prompt["genre_name"],
        "genre_slug":     prompt["genre_slug"],
        "bpm":            prompt["bpm"],
        "title":          result["title"],
        "suno_clip_id":   result["suno_clip_id"],
        "style_prompt":   prompt["style_prompt"],
        "mp3_path":       result["mp3_path"],
        "cover_path":     result.get("cover_path", ""),
        "audio_url":      result.get("audio_url", ""),
        "status":         result["status"],   # "downloaded" | "demo"
        "youtube_status": "pending",
        "phase":          "1-generated",
        "notes":          "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# メインパイプライン
# ─────────────────────────────────────────────────────────────────────────────
def run_pipeline(genre_filter: str | None = None) -> None:
    logger.info("═" * 65)
    logger.info("  All k Music — Suno AI 楽曲資産蓄積システム 初号機")
    logger.info("  %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("═" * 65)

    # ── 設定読み込み ─────────────────────────────────────────────────────
    config = SunoConfig(CONFIG_PATH)
    if config.is_demo:
        logger.warning("⚠  DEMO MODE: Cookie 未設定 → プレースホルダーを生成します")
        logger.warning("   config/suno_config.json の 'cookie' に Suno セッション Cookie を設定してください")
    else:
        logger.info("✓  LIVE MODE: Cookie 確認済み → Suno AI に接続します")

    downloader = SunoDownloader(config, TRACKS_DIR, COVERS_DIR)
    curator    = TrendCurator()

    # ── セッションプロンプト生成 ──────────────────────────────────────────
    all_prompts = curator.curate_session()
    if genre_filter:
        all_prompts = [p for p in all_prompts if p["genre_slug"] == genre_filter]
        if not all_prompts:
            logger.error("ジャンル '%s' が見つかりません。利用可能: lofi, edm, ambient, synthwave", genre_filter)
            sys.exit(1)

    logger.info("処理キュー: %d ジャンル", len(all_prompts))

    # ── 既存ログ読み込み ─────────────────────────────────────────────────
    asset_log     = load_asset_log()
    base_index    = len(asset_log) + 1
    session_results: list = []

    # ── メインループ ─────────────────────────────────────────────────────
    for i, prompt in enumerate(all_prompts):
        global_idx = base_index + i
        genre = prompt["genre_name"]
        logger.info(
            "\n── %d/%d: %s (BPM=%d) %s",
            i + 1, len(all_prompts), genre, prompt["bpm"],
            "─" * max(0, 50 - len(genre)),
        )
        logger.info("   スタイルプロンプト: %s", prompt["style_prompt"])

        try:
            result = downloader.generate_and_download(prompt, global_idx)
        except Exception as exc:
            logger.error("[Pipeline] 予期せぬエラー: %s — スキップ", exc)
            continue

        if result is None:
            logger.error("[Pipeline] %s をスキップしました", genre)
            continue

        entry = build_log_entry(prompt, result)
        asset_log.append(entry)
        session_results.append(entry)

        # 1 曲ごとに即時保存（途中でクラッシュしても損失を最小化）
        save_asset_log(asset_log)
        logger.info("[Log] ✓ 記録済み: %s / %s", result["asset_id"], result["title"])

    # ── セッションサマリー ────────────────────────────────────────────────
    downloaded = sum(1 for e in session_results if e["status"] == "downloaded")
    demo_count = sum(1 for e in session_results if e["status"] == "demo")

    logger.info("\n" + "═" * 65)
    logger.info("  セッション完了")
    logger.info("  処理: %d/%d ジャンル", len(session_results), len(all_prompts))
    logger.info("  実ダウンロード: %d 曲  |  DEMO: %d 曲", downloaded, demo_count)
    logger.info("  累計資産総数: %d トラック", len(asset_log))
    logger.info("  ログ: %s", ASSET_LOG)
    logger.info("═" * 65)


# ─────────────────────────────────────────────────────────────────────────────
# CLI エントリポイント
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="All k Music — Suno AI 楽曲生成パイプライン",
    )
    parser.add_argument(
        "--genre",
        choices=["lofi", "edm", "ambient", "synthwave"],
        default=None,
        help="特定ジャンルのみ実行 (未指定で全4ジャンル)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_pipeline(genre_filter=args.genre)
