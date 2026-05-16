"""
Video Encoder — All k Music
────────────────────────────────────────────────────────────────────────
ffmpeg ラッパーで「1時間 MP4（通常動画）」と「60秒 Shorts」を出力する。

既存パターン (youtube-video-encoder / shorts-generator) 踏襲:
  通常動画:
    -loop 1 -framerate 2 -i thumb.png -i audio.mp3
    -c:v libx264 -tune stillimage -crf 28 -pix_fmt yuv420p
    -c:a aac -b:a 192k -shortest

  Shorts (60秒):
    -t 60 でトリム
    -vf crop=405:720:437:0,scale=1080:1920
    縦長 9:16 (1080×1920)
    ソース解像度 1280×720 → crop=405:720:437:0 で中央正方形 → scale で縦長に引き伸ばす
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _run(cmd: list, label: str = "") -> bool:
    """ffmpeg コマンドを実行して成否を返す。"""
    logger.debug("[ffmpeg:%s] %s", label, " ".join(str(c) for c in cmd[:8]))
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except FileNotFoundError:
        logger.error("[ffmpeg] ffmpeg が見つかりません。brew install ffmpeg で導入してください。")
        return False
    except subprocess.CalledProcessError as exc:
        logger.error("[ffmpeg:%s] 失敗:\n%s", label, exc.stderr[-800:])
        return False


# ── 通常動画 (1時間 MP4) ─────────────────────────────────────────────────
def encode_long_video(
    thumbnail: Path,
    audio: Path,
    out_path: Path,
    duration: int = 3600,
) -> Optional[Path]:
    """
    静止画サムネイル + 1時間メドレー音声 → 1時間 MP4 を生成する。

    Args:
        thumbnail: 1280×720 PNG/JPEG
        audio:     1時間 MP3
        out_path:  出力先 MP4
        duration:  秒数 (デフォルト 3600)

    Returns:
        生成された MP4 の Path。失敗時は None。
    """
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
        "-t", str(duration),
        "-shortest",
        str(out_path),
    ]
    ok = _run(cmd, label="long_video")
    if ok:
        size_mb = out_path.stat().st_size / 1_048_576
        logger.info("[VideoEncoder] ✓ 通常動画: %s  (%.1f MB)", out_path.name, size_mb)
        return out_path
    return None


# ── Shorts (縦型 60秒) ────────────────────────────────────────────────────
def encode_shorts(
    thumbnail: Path,
    audio: Path,
    out_path: Path,
    shorts_duration: int = 60,
) -> Optional[Path]:
    """
    1280×720 サムネイル + 音声 → 1080×1920 縦型 Shorts MP4 (60秒) を生成する。

    crop パラメータ (既存パターン踏襲):
      ソース 1280×720 → crop=405:720:437:0 → 405×720 の中央帯
      → scale=1080:1920 で縦長に

    Args:
        thumbnail:       1280×720 PNG/JPEG
        audio:           MP3 (60秒以上)
        out_path:        出力先 MP4
        shorts_duration: 秒数 (デフォルト 60)

    Returns:
        生成された Shorts MP4 の Path。失敗時は None。
    """
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
        "-t", str(shorts_duration),
        "-shortest",
        str(out_path),
    ]
    ok = _run(cmd, label="shorts")
    if ok:
        size_mb = out_path.stat().st_size / 1_048_576
        logger.info("[ShortsEncoder] ✓ Shorts: %s  (%.1f MB)", out_path.name, size_mb)
        return out_path
    return None


# ── パブリック API: 両形式を一括出力 ─────────────────────────────────────
def encode_all(
    thumbnail: Path,
    audio: Path,
    out_dir: Path,
    stem: str,
    shorts_duration: int = 60,
) -> dict:
    """
    通常動画 + Shorts を両方生成して結果 dict を返す。

    Returns:
        {"long": Path|None, "shorts": Path|None}
    """
    long_path   = out_dir / f"{stem}_1h.mp4"
    shorts_path = out_dir / f"{stem}_shorts.mp4"

    long_result   = encode_long_video(thumbnail, audio, long_path)
    shorts_result = encode_shorts(thumbnail, audio, shorts_path, shorts_duration)

    return {"long": long_result, "shorts": shorts_result}
