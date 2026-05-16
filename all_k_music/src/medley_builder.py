"""
Medley Builder — All k Music (Phase 3)
──────────────────────────────────────────────────────────────────────────────
既存パターン (audio-track-builder) を踏襲し、ジャンル別「神繋ぎ」で
複数の MP3 を 1 時間メドレーに結合する ffmpeg ラッパー。

ジャンル別トランジション:
  lofi      → acrossfade d=3 tri     + 低域EQ equalizer f=60
  edm       → 残響エコー aecho       + acrossfade d=1 squ (ハードカット気味)
  ambient   → 超スローフェード d=8 exp + ディープリバーブ aecho 1000ms
  synthwave → テープ感 d=2 log       + 中高域EQ equalizer f=120

重要な実装ルール (既存パターン踏襲):
  - ループは -stream_loop N (-aloop フィルター禁止)
  - LOOPS_NEEDED = ceil(SEGMENT_DURATION / src_dur) + 1
  - 複数ファイルの crossfade は複合 filtergraph で 1 pass 処理
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── 定数 ─────────────────────────────────────────────────────────────────────
SEGMENT_DURATION = 450        # 7分30秒 / セグメント (既存パターン踏襲)
TARGET_TOTAL_SEC = 3600       # 1時間
NUM_SEGMENTS     = TARGET_TOTAL_SEC // SEGMENT_DURATION   # 8セグメント

# ── ジャンル別設定 ────────────────────────────────────────────────────────────
GENRE_CONFIG: dict = {
    "lofi": {
        "label":          "Lo-fi Crossfade (3s tri)",
        "crossfade_sec":  3.0,
        "crossfade_curve": "tri",    # 三角形カーブ — なめらかなLo-fiに最適
        "eq_odd":  "equalizer=f=60:width_type=o:width=2:g=2",   # 低域ブースト
        "eq_even": "equalizer=f=100:width_type=o:width=2:g=1",  # 中低域
    },
    "edm": {
        "label":          "EDM Echo Drop (1s squ)",
        "crossfade_sec":  1.0,
        "crossfade_curve": "squ",    # スクエアカーブ — ハードドロップ感
        "eq_odd":  "aecho=0.8:0.88:60:0.4",           # 残響エコー (既存パターン)
        "eq_even": "equalizer=f=80:width_type=o:width=1:g=4",   # キック帯強調
    },
    "ambient": {
        "label":          "Ambient Deep Fade (8s exp)",
        "crossfade_sec":  8.0,
        "crossfade_curve": "exp",    # 指数カーブ — 境界が消える超スムーズ感
        "eq_odd":  "aecho=0.9:0.9:1000:0.3",          # ディープリバーブ 1000ms
        "eq_even": "equalizer=f=40:width_type=o:width=2:g=2",   # 超低域浮上
    },
    "synthwave": {
        "label":          "Synthwave Tape Fade (2s log)",
        "crossfade_sec":  2.0,
        "crossfade_curve": "log",    # 対数カーブ — テープ感のある立ち上がり
        "eq_odd":  "equalizer=f=120:width_type=o:width=2:g=3",  # 中高域
        "eq_even": "aecho=0.7:0.9:80:0.5",            # ショートエコー
    },
}


# ── ユーティリティ ─────────────────────────────────────────────────────────────
def _ffmpeg(*args, label: str = "") -> bool:
    """ffmpeg コマンドを実行して成否を返す。"""
    cmd = ["ffmpeg", "-y", *args]
    logger.debug("[ffmpeg:%s] %s", label, " ".join(str(a) for a in args[:6]))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except FileNotFoundError:
        logger.error("[ffmpeg] ffmpeg が見つかりません。brew install ffmpeg で導入してください。")
        return False
    except subprocess.CalledProcessError as exc:
        logger.error("[ffmpeg:%s] 失敗:\n%s", label, exc.stderr[-800:])
        return False


def _probe_duration(path: Path) -> float:
    """ffprobe で音声の長さ（秒）を取得する。取得失敗時は 180.0 を返す。"""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, check=True,
        )
        return float(r.stdout.strip())
    except Exception as exc:
        logger.warning("[ffprobe] %s の長さ取得失敗: %s", path.name, exc)
        return 180.0


def _check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


# ── セグメント生成 ─────────────────────────────────────────────────────────────
def _build_segment(src: Path, out: Path, eq_filter: str, duration: float) -> Optional[Path]:
    """
    ソース MP3 を -stream_loop でループし eq を適用、duration 秒にトリムする。
    ループ数: ceil(duration / src_dur) + 1  ← 既存パターン踏襲
    """
    src_dur = _probe_duration(src)
    loops   = math.ceil(duration / src_dur) + 1
    ok = _ffmpeg(
        "-stream_loop", str(loops), "-i", str(src),
        "-af", f"{eq_filter},atrim=0:{duration},asetpts=PTS-STARTPTS",
        "-t", str(duration), "-q:a", "2", str(out),
        label=f"seg:{out.stem}",
    )
    return out if ok else None


# ── 複合 filtergraph crossfade (シングルパス) ─────────────────────────────────
def _crossfade_all(segs: List[Path], cf_sec: float, curve: str, out: Path) -> bool:
    """
    N 個のセグメントを 1 回の ffmpeg で acrossfade 結合する。
    filtergraph:
      [0][1]acrossfade=d=X:c1=C:c2=C[m0];
      [m0][2]acrossfade=d=X:c1=C:c2=C[m1]; ...
    """
    if len(segs) == 1:
        shutil.copy(str(segs[0]), str(out))
        return True

    n = len(segs)
    parts = []
    for i in range(n - 1):
        a   = f"[{i}]"   if i == 0 else f"[m{i-1}]"
        b   = f"[{i+1}]"
        o   = f"[m{i}]"  if i < n - 2 else "[cfout]"
        parts.append(f"{a}{b}acrossfade=d={cf_sec}:c1={curve}:c2={curve}{o}")

    cmd  = ["ffmpeg", "-y"]
    for s in segs:
        cmd += ["-i", str(s)]
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[cfout]",
        "-q:a", "2", str(out),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except FileNotFoundError:
        logger.error("[ffmpeg] ffmpeg が見つかりません。")
        return False
    except subprocess.CalledProcessError as exc:
        logger.error("[crossfade_all] filtergraph 失敗:\n%s", exc.stderr[-800:])
        return False


# ── パブリック API ─────────────────────────────────────────────────────────────
def build_medley(
    mp3_paths: List[Path],
    genre_slug: str,
    out_dir: Path,
    out_stem: str,
) -> Optional[Path]:
    """
    複数の MP3 → ジャンル別「神繋ぎ」→ 1 時間メドレー MP3

    Args:
        mp3_paths:  ダウンロード済み MP3 のリスト
        genre_slug: "lofi" | "edm" | "ambient" | "synthwave"
        out_dir:    出力先ディレクトリ
        out_stem:   出力ファイル名 (拡張子なし)

    Returns:
        生成されたメドレー MP3 の Path。失敗時は None。
    """
    if not _check_ffmpeg():
        logger.error("[MedleyBuilder] ffmpeg が見つかりません。brew install ffmpeg で導入してください。")
        return None

    if not mp3_paths:
        logger.error("[MedleyBuilder] MP3 ファイルが 0 件です。")
        return None

    cfg     = GENRE_CONFIG.get(genre_slug, GENRE_CONFIG["lofi"])
    cf_sec  = cfg["crossfade_sec"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{out_stem}.mp3"

    logger.info("[MedleyBuilder] ─────────────────────────────────────────")
    logger.info("[MedleyBuilder] ジャンル : %s", genre_slug)
    logger.info("[MedleyBuilder] 繋ぎ方   : %s", cfg["label"])
    logger.info("[MedleyBuilder] ソース   : %d ファイル → %d セグメント", len(mp3_paths), NUM_SEGMENTS)

    # ソース不足の場合はループ補充
    sources = (mp3_paths * (NUM_SEGMENTS // len(mp3_paths) + 2))[:NUM_SEGMENTS]

    with tempfile.TemporaryDirectory(prefix="allk_medley_") as tmpdir:
        tmp = Path(tmpdir)

        # ── Step 1: セグメントファイル生成 ──────────────────────────────
        seg_files: List[Path] = []
        for i, src in enumerate(sources):
            eq  = cfg["eq_odd"] if i % 2 == 0 else cfg["eq_even"]
            dst = tmp / f"seg_{i:02d}.mp3"
            logger.info("  [seg %d/%d] %s  +  %s", i + 1, NUM_SEGMENTS, src.name, eq[:35])
            built = _build_segment(src, dst, eq, SEGMENT_DURATION)
            if built:
                seg_files.append(built)
            else:
                logger.warning("  [seg %d] 失敗 — スキップ", i + 1)

        if not seg_files:
            logger.error("[MedleyBuilder] 有効セグメントなし — 中断")
            return None

        # ── Step 2: crossfade で全セグメントを 1 pass 結合 ──────────────
        logger.info("[MedleyBuilder] crossfade 結合 (%d segs, curve=%s, d=%.1fs) …",
                    len(seg_files), cfg["crossfade_curve"], cf_sec)
        merged = tmp / "merged.mp3"
        ok = _crossfade_all(seg_files, cf_sec, cfg["crossfade_curve"], merged)
        if not ok:
            logger.error("[MedleyBuilder] crossfade 失敗 — concat に切り替え")
            # フォールバック: 単純 concat
            list_file = tmp / "list.txt"
            list_file.write_text(
                "\n".join(f"file '{s}'" for s in seg_files), encoding="utf-8"
            )
            ok = _ffmpeg(
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-q:a", "2", str(merged),
                label="concat_fallback",
            )
            if not ok:
                return None

        # ── Step 3: 1時間丁度にトリム ───────────────────────────────────
        logger.info("[MedleyBuilder] 最終トリム → %ds (%.0f分)", TARGET_TOTAL_SEC, TARGET_TOTAL_SEC / 60)
        trim_ok = _ffmpeg(
            "-i", str(merged),
            "-af", f"atrim=0:{TARGET_TOTAL_SEC},asetpts=PTS-STARTPTS",
            "-t", str(TARGET_TOTAL_SEC),
            "-q:a", "2", str(out_path),
            label="final_trim",
        )
        if not trim_ok:
            shutil.copy(str(merged), str(out_path))

    final_dur = _probe_duration(out_path)
    size_mb   = out_path.stat().st_size / 1_048_576
    logger.info("[MedleyBuilder] ✓ 完成: %s  (%.0fs / %.1f分 / %.1f MB)",
                out_path.name, final_dur, final_dur / 60, size_mb)
    return out_path
