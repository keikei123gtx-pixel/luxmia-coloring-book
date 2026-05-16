#!/usr/bin/env python3
"""
All k Music — メイン実行スクリプト
════════════════════════════════════════════════════════════════════════════
フルパイプライン:
  Phase 1: Suno AI 楽曲生成・ダウンロード → music_assets.json
  Phase 2: 神繋ぎメドレー生成 (medley_builder) + サムネイル生成 (thumbnail_maker)
  Phase 3: 動画エンコード (video_encoder) + SEO パッケージ生成 (seo_writer)

使用方法:
  cd all_k_music
  python main.py                  # Phase 1 のみ (Suno 生成)
  python main.py --phase 1        # Phase 1 のみ
  python main.py --phase 2        # Phase 2 のみ (メドレー + サムネイル)
  python main.py --phase 3        # Phase 3 のみ (動画 + SEO)
  python main.py --phase all      # 全フェーズ連続実行
  python main.py --genre lofi     # 特定ジャンルのみ (Phase 1)
════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── パス解決 ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.trend_curator import TrendCurator
from src.suno_downloader import SunoConfig, SunoDownloader
from src.medley_builder import build_medley, SEGMENT_DURATION, NUM_SEGMENTS
from src.thumbnail_maker import make_thumbnail
from src.video_encoder import encode_all
from src.seo_writer import generate_seo_package, save_seo_txt

# ── ロギング設定 ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── パス定数 ──────────────────────────────────────────────────────────────
CONFIG_PATH  = ROOT / "config" / "suno_config.json"
TRACKS_DIR   = ROOT / "assets" / "tracks"
COVERS_DIR   = ROOT / "assets" / "covers"
MEDLEY_DIR   = ROOT / "assets" / "medley"
THUMB_DIR    = ROOT / "assets" / "thumbnails"
VIDEO_DIR    = ROOT / "assets" / "videos"
SEO_DIR      = ROOT / "assets" / "seo"
ASSET_LOG    = ROOT / "logs" / "music_assets.json"


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
        "status":         result["status"],
        "youtube_status": "pending",
        "phase":          "1-generated",
        "notes":          "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: Suno AI 楽曲生成
# ─────────────────────────────────────────────────────────────────────────────
def run_phase1(genre_filter: Optional[str] = None) -> None:
    logger.info("════════════════════════════════════════════════════════════")
    logger.info("  Phase 1 — Suno AI 楽曲資産蓄積")
    logger.info("════════════════════════════════════════════════════════════")

    config = SunoConfig(CONFIG_PATH)
    if config.is_demo:
        logger.warning("⚠  DEMO MODE: Cookie 未設定 → プレースホルダーを生成します")
    else:
        logger.info("✓  LIVE MODE: Cookie 確認済み → Suno AI に接続します")

    downloader = SunoDownloader(config, TRACKS_DIR, COVERS_DIR)
    curator    = TrendCurator()

    all_prompts = curator.curate_session()
    if genre_filter:
        all_prompts = [p for p in all_prompts if p["genre_slug"] == genre_filter]
        if not all_prompts:
            logger.error("ジャンル '%s' が見つかりません。", genre_filter)
            sys.exit(1)

    asset_log  = load_asset_log()
    base_index = len(asset_log) + 1

    for i, prompt in enumerate(all_prompts):
        global_idx = base_index + i
        genre = prompt["genre_name"]
        logger.info("\n── %d/%d: %s (BPM=%d)", i + 1, len(all_prompts), genre, prompt["bpm"])
        logger.info("   スタイルプロンプト: %s", prompt["style_prompt"])

        try:
            result = downloader.generate_and_download(prompt, global_idx)
        except Exception as exc:
            logger.error("[Phase1] 予期せぬエラー: %s — スキップ", exc)
            continue

        if result is None:
            logger.error("[Phase1] %s をスキップしました", genre)
            continue

        entry = build_log_entry(prompt, result)
        asset_log.append(entry)
        save_asset_log(asset_log)
        logger.info("[Phase1] ✓ 記録済み: %s / %s", result["asset_id"], result["title"])

    downloaded = sum(1 for e in asset_log if e["status"] == "downloaded")
    demo_count = sum(1 for e in asset_log if e["status"] == "demo")
    logger.info("\n[Phase1] 完了 — ダウンロード: %d  DEMO: %d  累計: %d",
                downloaded, demo_count, len(asset_log))


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: メドレー生成 + サムネイル生成
# ─────────────────────────────────────────────────────────────────────────────
def run_phase2(genre_filter: Optional[str] = None) -> None:
    logger.info("════════════════════════════════════════════════════════════")
    logger.info("  Phase 2 — 神繋ぎメドレー生成 + サムネイル生成")
    logger.info("════════════════════════════════════════════════════════════")

    asset_log = load_asset_log()
    if not asset_log:
        logger.error("[Phase2] music_assets.json が空です。先に Phase 1 を実行してください。")
        return

    # ジャンル別に MP3 をグループ化
    from collections import defaultdict
    by_genre: dict = defaultdict(list)
    for entry in asset_log:
        slug = entry.get("genre_slug", "")
        mp3  = entry.get("mp3_path", "")
        if slug and mp3 and not mp3.endswith(".placeholder"):
            p = Path(mp3)
            if p.exists():
                by_genre[slug].append(p)

    # DEMO モード: placeholder → 実 MP3 がないのでスキップ
    if not any(by_genre.values()):
        logger.warning("[Phase2] 実 MP3 が 0 件 (DEMO MODE の可能性)。")
        logger.warning("         Suno Cookie を設定して Phase 1 を再実行するか、")
        logger.warning("         assets/tracks/ に MP3 を手動配置してください。")
        # DEMOでも続行できるよう tracks ディレクトリを直接スキャンする
        for slug in ["lofi", "edm", "ambient", "synthwave"]:
            if genre_filter and slug != genre_filter:
                continue
            mp3s = list(TRACKS_DIR.glob(f"*{slug}*.mp3"))
            if mp3s:
                by_genre[slug] = mp3s
                logger.info("[Phase2] tracks/ からスキャン: %s → %d 件", slug, len(mp3s))

    slugs = list(by_genre.keys())
    if genre_filter:
        slugs = [s for s in slugs if s == genre_filter]

    for slug in slugs:
        mp3s = by_genre[slug]
        if not mp3s:
            logger.warning("[Phase2] %s: MP3 なし — スキップ", slug)
            continue

        logger.info("\n── Phase2: %s (%d tracks)", slug, len(mp3s))

        # ── メドレー生成 ─────────────────────────────────────────────
        stem   = f"{datetime.now().strftime('%Y%m%d')}_{slug}_medley"
        medley = build_medley(mp3s, slug, MEDLEY_DIR, stem)
        if not medley:
            logger.error("[Phase2] %s メドレー生成失敗", slug)
            continue
        logger.info("[Phase2] ✓ メドレー: %s", medley.name)

        # ── サムネイル生成 ──────────────────────────────────────────
        thumb_path = THUMB_DIR / f"{stem}.jpg"
        thumb = make_thumbnail(slug, stem, thumb_path)
        if not thumb:
            logger.warning("[Phase2] %s サムネイル生成失敗", slug)

        # ── アセットログ更新 ────────────────────────────────────────
        for entry in asset_log:
            if entry.get("genre_slug") == slug and entry.get("phase") == "1-generated":
                entry["phase"]      = "2-medley"
                entry["notes"]      = f"medley={medley.name}"
                if thumb:
                    entry["cover_path"] = str(thumb)
                break
        save_asset_log(asset_log)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: 動画エンコード + SEO テキスト生成
# ─────────────────────────────────────────────────────────────────────────────
def run_phase3(genre_filter: Optional[str] = None) -> None:
    logger.info("════════════════════════════════════════════════════════════")
    logger.info("  Phase 3 — 動画エンコード + SEO パッケージ生成")
    logger.info("════════════════════════════════════════════════════════════")

    asset_log = load_asset_log()
    if not asset_log:
        logger.error("[Phase3] music_assets.json が空です。Phase 1/2 を先に実行してください。")
        return

    # Phase 2 完了エントリのみ対象
    phase2_entries = [e for e in asset_log if e.get("phase") == "2-medley"]
    if not phase2_entries:
        # Phase 2 エントリがなければ medley ディレクトリを直接スキャン
        logger.warning("[Phase3] phase=2-medley のエントリなし。medley/ をスキャンします。")
        for medley_mp3 in sorted(MEDLEY_DIR.glob("*.mp3")):
            slug = next((s for s in ["lofi", "edm", "ambient", "synthwave"]
                         if s in medley_mp3.name), None)
            if not slug:
                continue
            if genre_filter and slug != genre_filter:
                continue
            _encode_for_slug(slug, medley_mp3, asset_log)
        save_asset_log(asset_log)
        return

    for entry in phase2_entries:
        slug = entry.get("genre_slug", "")
        if genre_filter and slug != genre_filter:
            continue

        notes = entry.get("notes", "")
        medley_name = notes.replace("medley=", "") if notes.startswith("medley=") else ""
        medley_path = MEDLEY_DIR / medley_name if medley_name else None

        if not medley_path or not medley_path.exists():
            # フォールバック: ディレクトリから最新 MP3 を探す
            candidates = sorted(MEDLEY_DIR.glob(f"*{slug}*.mp3"), reverse=True)
            medley_path = candidates[0] if candidates else None

        if not medley_path:
            logger.warning("[Phase3] %s: メドレー MP3 が見つかりません — スキップ", slug)
            continue

        _encode_for_slug(slug, medley_path, asset_log, entry)

    save_asset_log(asset_log)


def _encode_for_slug(
    slug: str,
    medley_path: Path,
    asset_log: list,
    entry: Optional[dict] = None,
) -> None:
    logger.info("\n── Phase3: %s  |  %s", slug, medley_path.name)

    # ── サムネイル特定 ───────────────────────────────────────────────
    cover = entry.get("cover_path", "") if entry else ""
    thumb_path = Path(cover) if cover and Path(cover).exists() else None
    if not thumb_path:
        thumbs = sorted(THUMB_DIR.glob(f"*{slug}*.jpg"), reverse=True)
        thumb_path = thumbs[0] if thumbs else None
    if not thumb_path:
        # サムネイルなし → 生成
        stem = medley_path.stem
        thumb_path = THUMB_DIR / f"{stem}.jpg"
        make_thumbnail(slug, stem, thumb_path)

    # ── 動画エンコード ────────────────────────────────────────────────
    stem   = medley_path.stem
    result = encode_all(thumb_path, medley_path, VIDEO_DIR, stem)
    long_mp4   = result.get("long")
    shorts_mp4 = result.get("shorts")

    if long_mp4:
        logger.info("[Phase3] ✓ 通常動画: %s", long_mp4.name)
    else:
        logger.warning("[Phase3] %s 通常動画エンコード失敗", slug)

    if shorts_mp4:
        logger.info("[Phase3] ✓ Shorts: %s", shorts_mp4.name)
    else:
        logger.warning("[Phase3] %s Shorts エンコード失敗", slug)

    # ── SEO パッケージ ────────────────────────────────────────────────
    asset_id = entry.get("asset_id", stem) if entry else stem
    seo = generate_seo_package(slug, asset_id)
    seo_path = SEO_DIR / f"{stem}_seo.txt"
    save_seo_txt(seo, seo_path)
    logger.info("[Phase3] ✓ SEO: %s", seo_path.name)

    # ── ログ更新 ──────────────────────────────────────────────────────
    if entry:
        entry["phase"] = "3-video"
        entry["notes"] = (
            f"long={long_mp4.name if long_mp4 else 'FAILED'}  "
            f"shorts={shorts_mp4.name if shorts_mp4 else 'FAILED'}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# CLI エントリポイント
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="All k Music — YouTube BGM 完全自動化パイプライン",
    )
    parser.add_argument(
        "--phase",
        choices=["1", "2", "3", "all"],
        default="1",
        help="実行フェーズ: 1=Suno生成 / 2=メドレー+サムネイル / 3=動画+SEO / all=全フェーズ",
    )
    parser.add_argument(
        "--genre",
        choices=["lofi", "edm", "ambient", "synthwave"],
        default=None,
        help="特定ジャンルのみ実行 (未指定で全4ジャンル)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args  = _parse_args()
    phase = args.phase
    genre = args.genre

    logger.info("╔═══════════════════════════════════════════════════════════╗")
    logger.info("║  All k Music — YouTube BGM 完全自動化パイプライン           ║")
    logger.info("║  %s  Phase=%s  Genre=%s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), phase, genre or "all")
    logger.info("╚═══════════════════════════════════════════════════════════╝")

    if phase in ("1", "all"):
        run_phase1(genre_filter=genre)

    if phase in ("2", "all"):
        run_phase2(genre_filter=genre)

    if phase in ("3", "all"):
        run_phase3(genre_filter=genre)

    logger.info("\n✓ All k Music パイプライン完了")
