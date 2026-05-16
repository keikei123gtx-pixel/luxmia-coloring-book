"""
Human DNA Engine — All k Music
────────────────────────────────────────────────────────────────────────
「波形レベルでの完全差別化」モジュール。

100% AI生成の mp3 をそのまま使うと、他ユーザーと波形が完全一致し
YouTubeの Content ID システムに「同一コンテンツ」として誤判定される
リスクがある。このモジュールは、ffmpeg のみで：

  ① ジャンル別「環境音レイヤー」をうっすら重ねる
     - lofi      : ヴィニールクラックル (ピンクノイズ → 高域成形)
                  + ルームトーン (ブラウンノイズ → 低域成形)
     - edm       : デジタルエア (ホワイトノイズ → 超高域)
                  + サブルームハム (ピンク → 低域)
     - ambient   : ウィンドレイヤー (ブラウンノイズ → 中低域)
                  + フォレストエア (ピンク → 中域)
     - synthwave : テープヒス (ホワイト → 超高域)
                  + アナログハム (ピンク → 60Hz帯)

  ② 独自の「残響シグネチャー」を全体に極薄掛け
     - ジャンル固有の aecho パラメータ → 他者と波形レベルで乖離

  ③ トラック末尾にフェードアウト + 残響エコーテール
     - 最後数秒を固有のエコーで締めくくり、指紋化する

ミックス量:
  環境音レイヤー: -28dB 相当 (volume=0.04 / 0.03)
  → 人間の耳にはほぼ聞こえないが、波形 / FFT では完全に差異が生じる
  → Content ID のフィンガープリントアルゴリズムを欺く「固有DNA」となる

依存: ffmpeg のみ (追加 Python パッケージ不要)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── ジャンル別 DNA 定義 ────────────────────────────────────────────────────
GENRE_DNA: dict = {
    "lofi": {
        # ヴィニールクラックル: ピンクノイズを 3kHz–9kHz 帯域に絞る
        "layer_hi": "anoisesrc=color=pink:amplitude=0.018,highpass=f=3000,lowpass=f=9000",
        # ルームトーン: ブラウンノイズを 120Hz 以下に絞る
        "layer_lo": "anoisesrc=color=brown:amplitude=0.014,lowpass=f=120",
        # 残響シグネチャー: 500ms ウォームエコー (lo-fi 感)
        "echo_sig": "aecho=0.45:0.35:500:0.18",
        # vol_hi / vol_lo: -28dB / -30dB 相当
        "vol_hi": 0.040,
        "vol_lo": 0.032,
        "tail_fade_sec": 4.0,
    },
    "edm": {
        # デジタルエア: ホワイトノイズを 9kHz 以上に絞る
        "layer_hi": "anoisesrc=color=white:amplitude=0.010,highpass=f=9000",
        # サブルームハム: ピンクノイズを 50–200Hz
        "layer_lo": "anoisesrc=color=pink:amplitude=0.008,highpass=f=50,lowpass=f=200",
        # 残響シグネチャー: 180ms ショートエコー (ステージ感)
        "echo_sig": "aecho=0.60:0.45:180:0.22",
        "vol_hi": 0.030,
        "vol_lo": 0.025,
        "tail_fade_sec": 2.0,
    },
    "ambient": {
        # ウィンドレイヤー: ブラウンノイズを 80–600Hz
        "layer_hi": "anoisesrc=color=brown:amplitude=0.022,highpass=f=80,lowpass=f=600",
        # フォレストエア: ピンクノイズを 600–3000Hz
        "layer_lo": "anoisesrc=color=pink:amplitude=0.012,highpass=f=600,lowpass=f=3000",
        # 残響シグネチャー: 1200ms ディープエコー (洞窟・森林感)
        "echo_sig": "aecho=0.80:0.70:1200:0.40",
        "vol_hi": 0.045,
        "vol_lo": 0.030,
        "tail_fade_sec": 8.0,
    },
    "synthwave": {
        # テープヒス: ホワイトノイズを 7kHz 以上
        "layer_hi": "anoisesrc=color=white:amplitude=0.012,highpass=f=7000",
        # アナログハム: ピンクノイズを 55–400Hz
        "layer_lo": "anoisesrc=color=pink:amplitude=0.009,highpass=f=55,lowpass=f=400",
        # 残響シグネチャー: 150ms テープエコー (アナログシンセ感)
        "echo_sig": "aecho=0.55:0.50:150:0.30",
        "vol_hi": 0.035,
        "vol_lo": 0.028,
        "tail_fade_sec": 3.0,
    },
}


def _check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _probe_duration(path: Path) -> float:
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
        logger.warning("[HumanDNA] duration probe 失敗: %s", exc)
        return 3600.0


def apply_dna(
    src: Path,
    genre_slug: str,
    out: Path,
    noise_duration_pad: int = 200,
) -> Optional[Path]:
    """
    src MP3 にジャンル別環境音レイヤー + 残響シグネチャーを重ね、
    波形レベルで完全差別化した out MP3 を生成する。

    Args:
        src:               元メドレー MP3
        genre_slug:        "lofi" | "edm" | "ambient" | "synthwave"
        out:               出力先 MP3
        noise_duration_pad: ノイズソースの余裕秒数 (デフォルト +200s)

    Returns:
        生成した MP3 の Path。失敗時は None (src をそのままコピーして返す)。
    """
    if not _check_ffmpeg():
        logger.error("[HumanDNA] ffmpeg が見つかりません。brew install ffmpeg で導入してください。")
        return None

    dna = GENRE_DNA.get(genre_slug, GENRE_DNA["lofi"])
    src_dur = _probe_duration(src)
    noise_dur = int(src_dur) + noise_duration_pad

    # フェードアウト開始位置: 末尾 tail_fade_sec 秒前
    fade_start = max(0.0, src_dur - dna["tail_fade_sec"])

    # ── filter_complex 構築 ──────────────────────────────────────────────
    # [0] = メイン音声
    # [1] = 環境音レイヤー Hi
    # [2] = 環境音レイヤー Lo
    #
    # Step 1: ノイズ音量調整
    # Step 2: 3ストリームを amix (normalize=0 で相対音量を維持)
    # Step 3: 残響シグネチャー (aecho)
    # Step 4: 末尾フェードアウト
    filter_complex = (
        f"[1]volume={dna['vol_hi']:.4f}[n1];"
        f"[2]volume={dna['vol_lo']:.4f}[n2];"
        f"[0][n1][n2]amix=inputs=3:duration=first:normalize=0[mixed];"
        f"[mixed]{dna['echo_sig']}[echoed];"
        f"[echoed]afade=t=out:st={fade_start:.1f}:d={dna['tail_fade_sec']:.1f}[out]"
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        # メイン入力
        "-i", str(src),
        # 環境音レイヤー Hi (lavfi で直接生成)
        "-f", "lavfi", "-i", f"{dna['layer_hi']}:duration={noise_dur}",
        # 環境音レイヤー Lo
        "-f", "lavfi", "-i", f"{dna['layer_lo']}:duration={noise_dur}",
        # フィルターグラフ
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-q:a", "2",
        str(out),
    ]

    logger.info(
        "[HumanDNA] 適用開始: %s  genre=%s  dur=%.0fs  fade=%.1fs",
        src.name, genre_slug, src_dur, dna["tail_fade_sec"],
    )
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        size_mb = out.stat().st_size / 1_048_576
        logger.info("[HumanDNA] ✓ DNA 適用完了: %s  (%.1f MB)", out.name, size_mb)
        return out
    except FileNotFoundError:
        logger.error("[HumanDNA] ffmpeg が見つかりません。")
        return None
    except subprocess.CalledProcessError as exc:
        logger.error("[HumanDNA] ffmpeg 失敗:\n%s", exc.stderr[-600:])
        return None


def describe_dna(genre_slug: str) -> str:
    """ジャンルの DNA レシピを人間可読な文字列で返す (ログ・計画書用)。"""
    dna = GENRE_DNA.get(genre_slug)
    if not dna:
        return f"[Unknown genre: {genre_slug}]"
    return (
        f"LayerHi  : {dna['layer_hi'][:55]}\n"
        f"LayerLo  : {dna['layer_lo'][:55]}\n"
        f"Echo-sig : {dna['echo_sig']}\n"
        f"Vol      : Hi={dna['vol_hi']:.3f} ({20*__import__('math').log10(dna['vol_hi']):.1f}dB)"
        f"  Lo={dna['vol_lo']:.3f} ({20*__import__('math').log10(dna['vol_lo']):.1f}dB)\n"
        f"FadeTail : {dna['tail_fade_sec']}s"
    )
