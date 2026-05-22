#!/usr/bin/env python3
"""
All k Music — メイン実行スクリプト
════════════════════════════════════════════════════════════════════════════
フルパイプライン:
  Phase 0 : 企画・プロンプト出力モード (人間確認 → コピペ用)
  Phase 1 : Suno AI 楽曲生成・ダウンロード → music_assets.json + asset_vault.jsonl
  Phase 2 : 神繋ぎメドレー + Human DNA トッピング + サムネイル生成
  Phase 3 : 動画エンコード (MP4 + Shorts) + SEO パッケージ生成

使用方法:
  python main.py --phase 0        # 企画書出力 (コピペ確認モード)
  python main.py --phase 1        # Suno 生成のみ
  python main.py --phase 2        # メドレー + DNA + サムネイル
  python main.py --phase 3        # 動画 + SEO
  python main.py --phase all      # 全フェーズ連続実行
  python main.py --genre lofi     # 特定ジャンルのみ
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

# Phase 0 / 共通: 軽量モジュールのみトップレベルで import
from src.trend_curator import TrendCurator
from src.human_dna import describe_dna
from src.asset_vault import stamp_entry, append_vault, verify_entry, read_vault

# Phase 1-3 固有モジュールは各 run_phase*() 内で遅延 import
# → Phase 0 が Pillow / ffmpeg なしで動作できるようにする

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
VAULT_LOG    = ROOT / "logs" / "asset_vault.jsonl"     # 追記専用 証拠台帳
PLAN_LOG_DIR = ROOT / "logs" / "plans"


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


def build_log_entry(prompt: dict, result: dict) -> dict:
    base = {
        "asset_id":        result["asset_id"],
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "genre":           prompt["genre_name"],
        "genre_slug":      prompt["genre_slug"],
        "bpm":             prompt["bpm"],
        "title":           result["title"],
        "suno_clip_id":    result["suno_clip_id"],
        "style_prompt":    prompt["style_prompt"],
        "mp3_path":        result["mp3_path"],
        "cover_path":      result.get("cover_path", ""),
        "audio_url":       result.get("audio_url", ""),
        "status":          result["status"],
        "phase":           "1-generated",
        "notes":           "",
        # ── 証拠フィールド ────────────────────────────────────────────
        "generation_seed": result.get("generation_seed", 0),
        "prompt_fingerprint": result.get("prompt_fingerprint", ""),
        "origin":          "suno_original_generate",
        "is_remix":        False,
        "is_extend":       False,
    }
    # asset_vault.stamp_entry で上書きされた証拠フィールドがあれば優先
    for k in ("prompt_fingerprint", "generation_iso", "save_timestamp_iso"):
        if k in result:
            base[k] = result[k]
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Phase 0: 企画・プロンプト出力モード
# ─────────────────────────────────────────────────────────────────────────────
def run_phase0(genre_filter: Optional[str] = None) -> None:
    """
    セッションプロンプトを生成し、人間が確認・コピペできる形式で出力する。
    Suno AI への実際のリクエストは行わない。
    """
    DIVIDER = "═" * 65
    curator = TrendCurator()
    prompts = curator.curate_session()

    if genre_filter:
        prompts = [p for p in prompts if p["genre_slug"] == genre_filter]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    plan_path = PLAN_LOG_DIR / f"session_plan_{timestamp}.txt"
    PLAN_LOG_DIR.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append(DIVIDER)
    lines.append(f"  All k Music — 企画・プロンプト出力モード")
    lines.append(f"  生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(DIVIDER)
    lines.append("")
    lines.append("【商用安全チェック結果】")
    lines.append("  ✓ make_instrumental = True  (全ジャンル強制)")
    lines.append("  ✓ continue_clip_id  = None  (他者楽曲継続禁止)")
    lines.append("  ✓ is_remix          = False (リミックス禁止)")
    lines.append("  ✓ is_extend         = False (拡張生成禁止)")
    lines.append("  ✓ アーティスト名・著作権IPをタグから排除済み")
    lines.append("")

    for i, p in enumerate(prompts, 1):
        slug = p["genre_slug"]
        lines.append(DIVIDER)
        lines.append(f"  [{i}/{len(prompts)}] {p['genre_name']}  |  BPM {p['bpm']}  |  Seed {p['generation_seed']}")
        lines.append(DIVIDER)
        lines.append("")
        lines.append("【Suno AI へのコピペ用スタイルプロンプト】")
        lines.append(f"  {p['style_prompt']}")
        lines.append("")
        lines.append("【ネガティブプロンプト】")
        lines.append(f"  {p['negative_prompt']}")
        lines.append("")
        lines.append("【Human DNA レシピ (Phase 2 で自動適用)】")
        for dna_line in describe_dna(slug).splitlines():
            lines.append(f"  {dna_line}")
        lines.append("")
        lines.append(f"  フィンガープリント対象: SHA-256({p['style_prompt'][:30]}... | {p['generation_seed']})")
        lines.append("")

    lines.append(DIVIDER)
    lines.append("  ★ 上記プロンプトを Suno AI に手動入力する場合:")
    lines.append("    1. suno.ai にログイン → Create")
    lines.append("    2. Style of Music にスタイルプロンプトを貼り付け")
    lines.append("    3. 「Instrumental」にチェック (必須)")
    lines.append("    4. generate → ダウンロード → assets/tracks/ に配置")
    lines.append("")
    lines.append("  ★ 自動生成する場合: python main.py --phase 1")
    lines.append(DIVIDER)

    output = "\n".join(lines)

    # ターミナル出力
    print(output)

    # ファイル保存
    plan_path.write_text(output, encoding="utf-8")
    logger.info("\n[Phase0] 企画書を保存しました: %s", plan_path)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: Suno AI 楽曲生成
# ─────────────────────────────────────────────────────────────────────────────
def run_phase1(genre_filter: Optional[str] = None) -> None:
    from src.suno_downloader import SunoConfig, SunoDownloader  # noqa: PLC0415

    logger.info("════════════════════════════════════════════════════════════")
    logger.info("  Phase 1 — Suno AI 楽曲資産蓄積 + 証拠台帳記録")
    logger.info("════════════════════════════════════════════════════════════")

    config = SunoConfig(CONFIG_PATH)
    if config.is_demo:
        logger.warning("⚠  DEMO MODE: Cookie 未設定 → プレースホルダーを生成します")
    else:
        logger.info("✓  LIVE MODE: Cookie 確認済み → Suno AI に接続します")

    downloader = SunoDownloader(config, TRACKS_DIR, COVERS_DIR, vault_path=VAULT_LOG)
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
        logger.info(
            "\n── %d/%d: %s (BPM=%d)  Seed=%d",
            i + 1, len(all_prompts), genre, prompt["bpm"], prompt["generation_seed"],
        )
        logger.info("   スタイルプロンプト: %s", prompt["style_prompt"])

        try:
            result = downloader.generate_and_download(prompt, global_idx)
        except Exception as exc:
            logger.error("[Phase1] 予期せぬエラー: %s — スキップ", exc)
            continue

        if result is None:
            logger.error("[Phase1] %s をスキップしました", genre)
            continue

        # 証拠フィールドを stamp_entry で付与
        stamped = stamp_entry(result, prompt["generation_seed"], prompt["style_prompt"])
        entry   = build_log_entry(prompt, stamped)
        asset_log.append(entry)
        save_asset_log(asset_log)
        logger.info(
            "[Phase1] ✓ 記録済み: %s  fp=%s",
            result["asset_id"], stamped.get("prompt_fingerprint", "n/a"),
        )

    downloaded = sum(1 for e in asset_log if e["status"] == "downloaded")
    demo_count = sum(1 for e in asset_log if e["status"] == "demo")
    vault_count = len(read_vault(VAULT_LOG))
    logger.info(
        "\n[Phase1] 完了 — ダウンロード: %d  DEMO: %d  証拠台帳: %d 件",
        downloaded, demo_count, vault_count,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: メドレー + Human DNA + サムネイル
# ─────────────────────────────────────────────────────────────────────────────
def run_phase2(genre_filter: Optional[str] = None, style: str = "default") -> None:
    from src.medley_builder import build_medley  # noqa: PLC0415
    from src.human_dna import apply_dna          # noqa: PLC0415
    from src.thumbnail_maker import make_thumbnail, make_lofi_girl_bg  # noqa: PLC0415

    logger.info("════════════════════════════════════════════════════════════")
    logger.info("  Phase 2 — 神繋ぎメドレー + Human DNA トッピング + サムネイル")
    logger.info("════════════════════════════════════════════════════════════")

    asset_log = load_asset_log()
    if not asset_log:
        logger.error("[Phase2] music_assets.json が空。Phase 1 を先に実行してください。")
        return

    from collections import defaultdict
    by_genre: dict = defaultdict(list)
    for entry in asset_log:
        slug = entry.get("genre_slug", "")
        mp3  = entry.get("mp3_path", "")
        if slug and mp3 and not mp3.endswith(".placeholder"):
            p = Path(mp3)
            if p.exists():
                by_genre[slug].append(p)

    if not any(by_genre.values()):
        logger.warning("[Phase2] 実 MP3 が 0 件 (DEMO MODE)。tracks/ をスキャンします。")
        for slug in ["lofi", "edm", "ambient", "synthwave"]:
            if genre_filter and slug != genre_filter:
                continue
            mp3s = list(TRACKS_DIR.glob(f"*{slug}*.mp3"))
            if mp3s:
                by_genre[slug] = mp3s

    slugs = [s for s in by_genre if (not genre_filter or s == genre_filter)]

    for slug in slugs:
        mp3s = by_genre[slug]
        if not mp3s:
            logger.warning("[Phase2] %s: MP3 なし — スキップ", slug)
            continue

        logger.info("\n── Phase2: %s (%d tracks)", slug, len(mp3s))
        stem = f"{datetime.now().strftime('%Y%m%d')}_{slug}_medley"

        # ── Step 1: 神繋ぎメドレー生成 ──────────────────────────────────
        raw_medley = build_medley(mp3s, slug, MEDLEY_DIR, f"{stem}_raw")
        if not raw_medley:
            logger.error("[Phase2] %s メドレー生成失敗", slug)
            continue

        # ── Step 2: Human DNA トッピング (波形差別化) ────────────────────
        dna_out = MEDLEY_DIR / f"{stem}.mp3"
        logger.info("[Phase2] Human DNA 適用中: %s …", slug)
        logger.info("         %s", describe_dna(slug).replace("\n", "\n         "))
        dna_result = apply_dna(raw_medley, slug, dna_out)

        if dna_result:
            # DNA 適用成功 → raw を削除して DNA 版を使用
            try:
                raw_medley.unlink()
            except OSError:
                pass
            final_medley = dna_result
            logger.info("[Phase2] ✓ Human DNA 適用済み: %s", dna_result.name)
        else:
            # ffmpeg なし等でフォールバック → raw をそのまま使用
            logger.warning("[Phase2] DNA 適用スキップ → raw メドレーをそのまま使用")
            final_medley = raw_medley

        # ── Step 3: サムネイル生成 ──────────────────────────────────────
        thumb_path = THUMB_DIR / f"{stem}.jpg"
        thumb = make_thumbnail(slug, stem, thumb_path, style=style)
        if thumb:
            logger.info("[Phase2] ✓ サムネイル: %s", thumb.name)
        else:
            logger.warning("[Phase2] %s サムネイル生成失敗", slug)

        # ── Step 4: LoFi Girl 動画背景生成 (lofi_girl スタイル時のみ) ──
        if style == "lofi_girl":
            bg_path = THUMB_DIR / f"{stem}_bg.png"
            bg = make_lofi_girl_bg(slug, bg_path)
            if bg:
                logger.info("[Phase2] ✓ LoFi 背景: %s", bg.name)
            else:
                logger.warning("[Phase2] %s LoFi 背景生成失敗", slug)

        # ── ログ更新 ────────────────────────────────────────────────────
        for entry in asset_log:
            if entry.get("genre_slug") == slug and entry.get("phase") == "1-generated":
                entry["phase"] = "2-medley"
                entry["notes"] = f"medley={final_medley.name}  dna={'applied' if dna_result else 'skipped'}"
                if thumb:
                    entry["cover_path"] = str(thumb)
                break
        save_asset_log(asset_log)

    logger.info("[Phase2] ✓ 完了 (style=%s)", style)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: 動画エンコード + SEO
# ─────────────────────────────────────────────────────────────────────────────
def run_phase3(genre_filter: Optional[str] = None, style: str = "default") -> None:
    from src.video_encoder import encode_all          # noqa: PLC0415
    from src.seo_writer import generate_seo_package, save_seo_txt  # noqa: PLC0415
    from src.thumbnail_maker import make_thumbnail    # noqa: PLC0415

    logger.info("════════════════════════════════════════════════════════════")
    logger.info("  Phase 3 — 動画エンコード + SEO パッケージ生成")
    logger.info("════════════════════════════════════════════════════════════")

    asset_log = load_asset_log()
    phase2_entries = [e for e in asset_log if e.get("phase") == "2-medley"]

    if not phase2_entries:
        logger.warning("[Phase3] phase=2-medley エントリなし。medley/ をスキャンします。")
        for medley_mp3 in sorted(MEDLEY_DIR.glob("*.mp3")):
            if "raw" in medley_mp3.name:
                continue
            slug = next((s for s in ["lofi", "edm", "ambient", "synthwave"]
                         if s in medley_mp3.name), None)
            if not slug or (genre_filter and slug != genre_filter):
                continue
            _encode_for_slug(slug, medley_mp3, asset_log, style=style)
        save_asset_log(asset_log)
        return

    for entry in phase2_entries:
        slug = entry.get("genre_slug", "")
        if genre_filter and slug != genre_filter:
            continue
        notes = entry.get("notes", "")
        medley_name = notes.split("  ")[0].replace("medley=", "") if notes else ""
        medley_path = MEDLEY_DIR / medley_name if medley_name else None
        if not medley_path or not medley_path.exists():
            candidates = [p for p in sorted(MEDLEY_DIR.glob(f"*{slug}*.mp3"), reverse=True)
                          if "raw" not in p.name]
            medley_path = candidates[0] if candidates else None
        if not medley_path:
            logger.warning("[Phase3] %s: メドレー MP3 見つからず — スキップ", slug)
            continue
        _encode_for_slug(slug, medley_path, asset_log, entry, style=style)

    save_asset_log(asset_log)


def _encode_for_slug(
    slug: str,
    medley_path: Path,
    asset_log: list,
    entry: Optional[dict] = None,
    style: str = "default",
) -> None:
    from src.video_encoder import encode_all          # noqa: PLC0415
    from src.seo_writer import generate_seo_package, save_seo_txt  # noqa: PLC0415
    from src.thumbnail_maker import make_thumbnail    # noqa: PLC0415

    logger.info("\n── Phase3: %s  |  %s  |  style=%s", slug, medley_path.name, style)

    cover = entry.get("cover_path", "") if entry else ""
    thumb_path = Path(cover) if cover and Path(cover).exists() else None
    if not thumb_path:
        thumbs = [p for p in sorted(THUMB_DIR.glob(f"*{slug}*.jpg"), reverse=True)]
        thumb_path = thumbs[0] if thumbs else None
    if not thumb_path:
        stem = medley_path.stem
        thumb_path = THUMB_DIR / f"{stem}.jpg"
        make_thumbnail(slug, stem, thumb_path, style=style)

    stem = medley_path.stem

    # LoFi Girl スタイルの場合: 動画背景 PNG を探す
    bg_image = None
    if style == "lofi_girl":
        bgs = [p for p in sorted(THUMB_DIR.glob(f"*{slug}*_bg.png"), reverse=True)]
        if bgs:
            bg_image = bgs[0]
        else:
            # フォールバック: その場で生成
            from src.thumbnail_maker import make_lofi_girl_bg  # noqa: PLC0415
            bg_image = THUMB_DIR / f"{stem}_bg.png"
            make_lofi_girl_bg(slug, bg_image)
            if not bg_image.exists():
                bg_image = None

    result = encode_all(
        thumb_path, medley_path, VIDEO_DIR, stem,
        style=style, bg_image=bg_image, genre_slug=slug,
    )
    long_mp4   = result.get("long")
    shorts_mp4 = result.get("shorts")

    asset_id = entry.get("asset_id", stem) if entry else stem
    seo = generate_seo_package(slug, asset_id)
    seo_path = SEO_DIR / f"{stem}_seo.txt"
    save_seo_txt(seo, seo_path)

    if entry:
        entry["phase"] = "3-video"
        entry["notes"] = (
            f"long={long_mp4.name if long_mp4 else 'FAILED'}  "
            f"shorts={shorts_mp4.name if shorts_mp4 else 'FAILED'}"
        )

    logger.info("[Phase3] ✓ 完了: long=%s  shorts=%s  seo=%s",
                long_mp4.name if long_mp4 else "FAILED",
                shorts_mp4.name if shorts_mp4 else "FAILED",
                seo_path.name)


# ─────────────────────────────────────────────────────────────────────────────
# CLI エントリポイント
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="All k Music — YouTube BGM 完全自動化パイプライン",
    )
    parser.add_argument(
        "--phase",
        choices=["0", "1", "2", "3", "all"],
        default="0",
        help=(
            "実行フェーズ:\n"
            "  0   = 企画書出力 (コピペ確認モード)\n"
            "  1   = Suno 生成 + 証拠台帳記録\n"
            "  2   = メドレー + Human DNA + サムネイル\n"
            "  3   = 動画エンコード + SEO\n"
            "  all = 全フェーズ連続実行"
        ),
    )
    parser.add_argument(
        "--genre",
        choices=["lofi", "edm", "ambient", "synthwave"],
        default=None,
        help="特定ジャンルのみ実行 (未指定で全4ジャンル)",
    )
    parser.add_argument(
        "--style",
        choices=["default", "ncs", "lofi_girl"],
        default="default",
        help=(
            "動画スタイル:\n"
            "  default   = グラデーション背景 (従来スタイル)\n"
            "  ncs       = 黒背景 + EQ スペクトラムバー (NCS 風)\n"
            "  lofi_girl = 夜の部屋イラスト + 窓 (LoFi Girl 風)"
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args  = _parse_args()
    phase = args.phase
    genre = args.genre
    style = args.style

    if phase != "0":
        logger.info("╔═══════════════════════════════════════════════════════════╗")
        logger.info("║  All k Music — YouTube BGM 完全自動化パイプライン")
        logger.info("║  %s  Phase=%s  Genre=%s  Style=%s",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), phase, genre or "all", style)
        logger.info("╚═══════════════════════════════════════════════════════════╝")

    if phase in ("0",):
        run_phase0(genre_filter=genre)

    if phase in ("1", "all"):
        run_phase1(genre_filter=genre)

    if phase in ("2", "all"):
        run_phase2(genre_filter=genre, style=style)

    if phase in ("3", "all"):
        run_phase3(genre_filter=genre, style=style)

    if phase not in ("0",):
        logger.info("\n✓ All k Music パイプライン完了")
