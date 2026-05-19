"""
Video Encoder — All k Music
────────────────────────────────────────────────────────────────────────
3スタイルの動画 + Shorts を ffmpeg で生成する。

  default    : 静止サムネイル画像 + 音声 (従来方式)
  ncs        : NCS 風 — showcqt スペクトラム + ダーク背景 + ジャンル別カラー
  lofi_girl  : LoFi Girl 風 — コージー背景画像 + showwaves + 雨ノイズ + ビネット

依存: ffmpeg のみ
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── NCS スタイル: ジャンル別パラメータ ────────────────────────────────────
# cscheme: showcqt の色設定 (r1|g1|b1|r2|g2|b2, 各 0.0–1.0)
_NCS = {
    "lofi": {
        "cscheme": "1|0.65|0.05|0.9|0.4|0",
        "accent":  "FFA61A",
        "label":   "Lo-fi Hip Hop  |  1 Hour Study Mix",
        "bg":      "0x0D0D0D",
    },
    "edm": {
        "cscheme": "0|0.9|1|0|0.5|0.8",
        "accent":  "00E5FF",
        "label":   "EDM  |  1 Hour Festival Energy Mix",
        "bg":      "0x05000A",
    },
    "ambient": {
        "cscheme": "0.35|0.9|0.65|0.15|0.7|0.5",
        "accent":  "59E6A0",
        "label":   "Ambient  |  1 Hour Deep Relaxation Mix",
        "bg":      "0x020A0F",
    },
    "synthwave": {
        "cscheme": "1|0.3|0.8|0.7|0|0.5",
        "accent":  "FF4DCC",
        "label":   "Synthwave  |  1 Hour Night Drive Mix",
        "bg":      "0x0F0523",
    },
}

# ── LoFi Girl スタイル: ジャンル別波形カラー ──────────────────────────────
_LOFI_WAVE = {
    "lofi":      "FFD700",
    "edm":       "00E5FF",
    "ambient":   "7FFFD4",
    "synthwave": "FF69B4",
}


def _find_font() -> str:
    """使用可能なフォントパスを返す。見つからなければ空文字。"""
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/System/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]:
        if Path(p).exists():
            return p
    return ""


def _check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _run(cmd: list, label: str = "") -> bool:
    logger.debug("[ffmpeg:%s] %s", label, " ".join(str(c) for c in cmd[:10]))
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except FileNotFoundError:
        logger.error("[ffmpeg] ffmpeg が見つかりません。")
        return False
    except subprocess.CalledProcessError as exc:
        logger.error("[ffmpeg:%s] 失敗:\n%s", label, exc.stderr[-800:])
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Default スタイル (静止画)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def encode_long_video(
    thumbnail: Path,
    audio: Path,
    out_path: Path,
    duration: int = 3600,
) -> Optional[Path]:
    """静止画サムネイル + 1時間メドレー音声 → 1時間 MP4"""
    if not _check_ffmpeg():
        logger.error("[VideoEncoder] ffmpeg が見つかりません。")
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", "2", "-i", str(thumbnail),
        "-i", str(audio),
        "-c:v", "libx264", "-tune", "stillimage", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration), "-shortest",
        str(out_path),
    ]
    ok = _run(cmd, "long_video")
    if ok:
        size_mb = out_path.stat().st_size / 1_048_576
        logger.info("[VideoEncoder] ✓ 通常動画: %s  (%.1f MB)", out_path.name, size_mb)
        return out_path
    return None


def encode_shorts(
    thumbnail: Path,
    audio: Path,
    out_path: Path,
    shorts_duration: int = 60,
) -> Optional[Path]:
    """1280×720 サムネイル + 音声 → 1080×1920 縦型 Shorts MP4 (60秒)"""
    if not _check_ffmpeg():
        logger.error("[ShortsEncoder] ffmpeg が見つかりません。")
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vf = "crop=405:720:437:0,scale=1080:1920"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", "2", "-i", str(thumbnail),
        "-i", str(audio),
        "-vf", vf,
        "-c:v", "libx264", "-tune", "stillimage", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(shorts_duration), "-shortest",
        str(out_path),
    ]
    ok = _run(cmd, "shorts")
    if ok:
        size_mb = out_path.stat().st_size / 1_048_576
        logger.info("[ShortsEncoder] ✓ Shorts: %s  (%.1f MB)", out_path.name, size_mb)
        return out_path
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NCS スタイル
#   - showcqt (Constant-Q Transform) スペクトラムを画面下部に配置
#   - ジャンル別カラー + "ALL K MUSIC" ロゴ + ジャンル名テキスト
#   - 10fps / ultrafast / crf=32 で高速エンコード
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def encode_ncs_long(
    audio: Path,
    out_path: Path,
    genre_slug: str = "lofi",
    duration: int = 3600,
) -> Optional[Path]:
    """NCS 風 1時間動画 (1920×1080): showcqt スペクトラム + ダーク背景"""
    if not _check_ffmpeg():
        return None

    g = _NCS.get(genre_slug, _NCS["lofi"])
    font = _find_font()
    fa = f":fontfile={font}" if font else ""
    accent = g["accent"]
    label = g["label"]

    # showcqt 1920×380 を y=700 に配置 (上部 700px がテキスト領域)
    fc = (
        f"[0:a]showcqt=s=1920x380:count=1:bar_g=8:bar_v=9:"
        f"volume=0.7:tc=0.33:gamma=7:gamma2=2:"
        f"fontcolor=white@0:sono_v=0:bar_t=0.5:"
        f"cscheme={g['cscheme']}[spec];"
        f"[1:v]scale=1920:1080[bg];"
        f"[bg][spec]overlay=0:700[comp];"
        # アクセントライン (スペクトラム上端)
        f"[comp]drawbox=x=0:y=698:w=1920:h=3:"
        f"color=0x{accent}@0.8:t=fill[ln];"
        # 左縦アクセントバー (NCS 風)
        f"[ln]drawbox=x=65:y=238:w=5:h=185:"
        f"color=0x{accent}:t=fill[vb];"
        # チャンネルロゴ
        f"[vb]drawtext=text='ALL K MUSIC':"
        f"fontcolor=white:fontsize=88:x=88:y=245{fa}[logo];"
        # ジャンル + 内容ラベル
        f"[logo]drawtext=text='{label}':"
        f"fontcolor=0x{accent}:fontsize=42:x=88:y=348{fa}[final]"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio),
        "-f", "lavfi", "-i", f"color=c={g['bg']}:s=1920x1080:r=10",
        "-filter_complex", fc,
        "-map", "[final]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
        "-r", "10", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_path),
    ]
    ok = _run(cmd, "ncs_long")
    if ok:
        size_mb = out_path.stat().st_size / 1_048_576
        logger.info("[VideoEncoder] ✓ NCS通常動画: %s  (%.1f MB)", out_path.name, size_mb)
        return out_path
    return None


def encode_ncs_shorts(
    audio: Path,
    out_path: Path,
    genre_slug: str = "lofi",
    duration: int = 60,
) -> Optional[Path]:
    """NCS 風 Shorts (1080×1920 縦型): showcqt スペクトラム 下部配置"""
    if not _check_ffmpeg():
        return None

    g = _NCS.get(genre_slug, _NCS["lofi"])
    font = _find_font()
    fa = f":fontfile={font}" if font else ""
    accent = g["accent"]
    label_short = g["label"].split("|")[0].strip()

    # 1080×1920: スペクトラム 1080×500 を y=1420 に配置
    fc = (
        f"[0:a]showcqt=s=1080x500:count=1:bar_g=8:bar_v=9:"
        f"volume=0.7:tc=0.33:gamma=7:gamma2=2:"
        f"fontcolor=white@0:sono_v=0:bar_t=0.5:"
        f"cscheme={g['cscheme']}[spec];"
        f"[1:v]scale=1080:1920[bg];"
        f"[bg][spec]overlay=0:1420[comp];"
        f"[comp]drawbox=x=0:y=1418:w=1080:h=3:"
        f"color=0x{accent}@0.8:t=fill[ln];"
        f"[ln]drawbox=x=60:y=695:w=5:h=205:"
        f"color=0x{accent}:t=fill[vb];"
        f"[vb]drawtext=text='ALL K MUSIC':"
        f"fontcolor=white:fontsize=82:x=80:y=705{fa}[logo];"
        f"[logo]drawtext=text='{label_short}':"
        f"fontcolor=0x{accent}:fontsize=50:x=80:y=805{fa}[sub];"
        f"[sub]drawtext=text='1 Hour Mix':"
        f"fontcolor=white@0.7:fontsize=42:x=80:y=868{fa}[final]"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio),
        "-f", "lavfi", "-i", f"color=c={g['bg']}:s=1080x1920:r=10",
        "-filter_complex", fc,
        "-map", "[final]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
        "-r", "10", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_path),
    ]
    ok = _run(cmd, "ncs_shorts")
    if ok:
        size_mb = out_path.stat().st_size / 1_048_576
        logger.info("[ShortsEncoder] ✓ NCS Shorts: %s  (%.1f MB)", out_path.name, size_mb)
        return out_path
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LoFi Girl スタイル
#   - コージー背景画像 (Pillow 生成 1920×1080 PNG) を静止背景に
#   - showwaves で音楽波形を画面底に重ねる
#   - noise フィルタで雨エフェクト
#   - colorbalance でクール・夜間色調
#   - vignette でフィルム感
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def encode_lofi_girl_long(
    audio: Path,
    bg_image: Path,
    out_path: Path,
    genre_slug: str = "lofi",
    duration: int = 3600,
) -> Optional[Path]:
    """LoFi Girl 風 1時間動画: コージー背景 + 音楽波形 + 雨ノイズ + ビネット"""
    if not _check_ffmpeg():
        return None

    wc = _LOFI_WAVE.get(genre_slug, "FFD700")
    font = _find_font()
    fa = f":fontfile={font}" if font else ""

    fc = (
        f"[1:v]scale=1920:1080[bg];"
        # 音楽波形 (底部 90px)
        f"[0:a]showwaves=s=1920x90:mode=cline:"
        f"colors=0x{wc}@0.85:rate=30[wave];"
        f"[bg][wave]overlay=0:H-h-5[ww];"
        # 雨ノイズ (temporal noise)
        f"[ww]noise=alls=18:allf=a+t[rain];"
        # 夜間色調 (わずかに青寄り)
        f"[rain]colorbalance=rs=-0.05:gs=0:bs=0.07:"
        f"rm=-0.02:gm=0:bm=0.04[col];"
        # ビネット (周辺減光)
        f"[col]vignette=PI/4.5:PI/4.5[vign];"
        # チャンネルロゴ (右下・波形の上)
        f"[vign]drawtext=text='All k Music':"
        f"fontcolor=white@0.8:fontsize=34:"
        f"x=W-tw-30:y=H-th-105{fa}[final]"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio),
        "-loop", "1", "-i", str(bg_image),
        "-filter_complex", fc,
        "-map", "[final]", "-map", "0:a",
        "-c:v", "libx264", "-tune", "stillimage",
        "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_path),
    ]
    ok = _run(cmd, "lofi_girl_long")
    if ok:
        size_mb = out_path.stat().st_size / 1_048_576
        logger.info("[VideoEncoder] ✓ LoFiGirl通常動画: %s  (%.1f MB)", out_path.name, size_mb)
        return out_path
    return None


def encode_lofi_girl_shorts(
    audio: Path,
    bg_image: Path,
    out_path: Path,
    genre_slug: str = "lofi",
    duration: int = 60,
) -> Optional[Path]:
    """LoFi Girl 風 Shorts (縦型 60秒): 背景中央クロップ → 9:16 + 波形 + 雨"""
    if not _check_ffmpeg():
        return None

    wc = _LOFI_WAVE.get(genre_slug, "FFD700")
    font = _find_font()
    fa = f":fontfile={font}" if font else ""

    # 1920×1080 → 中央 607px 幅を切り抜き → 1080×1920 縦型
    fc = (
        f"[1:v]scale=1920:1080,crop=607:1080:656:0,scale=1080:1920[bg];"
        f"[0:a]showwaves=s=1080x90:mode=cline:"
        f"colors=0x{wc}@0.85:rate=30[wave];"
        f"[bg][wave]overlay=0:H-h-5[ww];"
        f"[ww]noise=alls=18:allf=a+t[rain];"
        f"[rain]colorbalance=rs=-0.05:gs=0:bs=0.07:"
        f"rm=-0.02:gm=0:bm=0.04[col];"
        f"[col]vignette=PI/4.5:PI/4.5[vign];"
        f"[vign]drawtext=text='All k Music':"
        f"fontcolor=white@0.8:fontsize=34:"
        f"x=W-tw-30:y=H-th-105{fa}[final]"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio),
        "-loop", "1", "-i", str(bg_image),
        "-filter_complex", fc,
        "-map", "[final]", "-map", "0:a",
        "-c:v", "libx264", "-tune", "stillimage",
        "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_path),
    ]
    ok = _run(cmd, "lofi_girl_shorts")
    if ok:
        size_mb = out_path.stat().st_size / 1_048_576
        logger.info("[ShortsEncoder] ✓ LoFiGirl Shorts: %s  (%.1f MB)", out_path.name, size_mb)
        return out_path
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# パブリック API: 両形式を一括出力
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def encode_all(
    thumbnail: Path,
    audio: Path,
    out_dir: Path,
    stem: str,
    shorts_duration: int = 60,
    style: str = "default",
    bg_image: Optional[Path] = None,
    genre_slug: str = "lofi",
) -> dict:
    """
    通常動画 + Shorts を両方生成して結果 dict を返す。

    Args:
        thumbnail:       サムネイル画像 (default / lofi_girl fallback 用)
        audio:           メドレー MP3
        out_dir:         出力ディレクトリ
        stem:            ファイル名ベース
        shorts_duration: Shorts 秒数
        style:           "default" | "ncs" | "lofi_girl"
        bg_image:        LoFi Girl 背景画像 (lofi_girl スタイル時に使用)
        genre_slug:      ジャンル識別子

    Returns:
        {"long": Path|None, "shorts": Path|None}
    """
    long_path   = out_dir / f"{stem}_1h.mp4"
    shorts_path = out_dir / f"{stem}_shorts.mp4"

    if style == "ncs":
        long_result   = encode_ncs_long(audio, long_path, genre_slug)
        shorts_result = encode_ncs_shorts(audio, shorts_path, genre_slug, shorts_duration)
    elif style == "lofi_girl" and bg_image and bg_image.exists():
        long_result   = encode_lofi_girl_long(audio, bg_image, long_path, genre_slug)
        shorts_result = encode_lofi_girl_shorts(audio, bg_image, shorts_path, genre_slug, shorts_duration)
    else:
        long_result   = encode_long_video(thumbnail, audio, long_path)
        shorts_result = encode_shorts(thumbnail, audio, shorts_path, shorts_duration)

    return {"long": long_result, "shorts": shorts_result}
