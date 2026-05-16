"""
Thumbnail Maker — All k Music
────────────────────────────────────────────────────────────────────────
PIL/Pillow で 1280×720 JPG サムネイルを生成する。

既存パターン (music-thumbnail) 踏襲:
  - JP + EN 別レイヤーで draw.text()
  - フィルムグレイン (np.random ノイズ)
  - ジャンル別カラーパレット
  - 出力: 1280×720 PNG → JPEG 変換 (q=95)
"""

from __future__ import annotations

import io
import logging
import random
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# ── ジャンル別カラーテーマ ────────────────────────────────────────────────
GENRE_THEME: dict = {
    "lofi": {
        "bg_top":    (28,  24,  38),   # ダークパープル
        "bg_bot":    (18,  30,  40),   # ダークネイビー
        "accent":    (255, 200, 100),  # ウォームイエロー
        "text_main": (240, 230, 200),  # クリームホワイト
        "text_sub":  (180, 170, 155),  # ウォームグレー
        "glow":      (255, 180,  80),  # アンバーグロー
    },
    "edm": {
        "bg_top":    (10,   5,  30),   # ディープネイビー
        "bg_bot":    (30,   5,  50),   # ダークバイオレット
        "accent":    (0,  230, 255),   # ネオンシアン
        "text_main": (220, 240, 255),  # クールホワイト
        "text_sub":  (130, 200, 255),  # ライトブルー
        "glow":      (80,  200, 255),  # シアングロー
    },
    "ambient": {
        "bg_top":    (5,   20,  30),   # ディープティール
        "bg_bot":    (10,  10,  25),   # ダークブルー
        "accent":    (100, 220, 180),  # ミントグリーン
        "text_main": (200, 235, 220),  # ソフトホワイト
        "text_sub":  (130, 190, 170),  # ソフトグリーン
        "glow":      (80,  200, 160),  # ティールグロー
    },
    "synthwave": {
        "bg_top":    (15,   5,  35),   # ダークパープル
        "bg_bot":    (35,   5,  25),   # ダークマゼンタ
        "accent":    (255,  80, 200),  # ホットピンク
        "text_main": (255, 220, 240),  # ピンクホワイト
        "text_sub":  (200, 150, 220),  # ラベンダー
        "glow":      (255,  60, 180),  # マゼンタグロー
    },
}

# ── ジャンル別日本語タイトルライン ───────────────────────────────────────
GENRE_JP_LINES: dict = {
    "lofi":      ("Lo-fi Hip Hop", "作業用 BGM"),
    "edm":       ("EDM Glitch Hop", "フェス系 BGM"),
    "ambient":   ("Ambient Healing", "睡眠・瞑想 BGM"),
    "synthwave": ("Synthwave Retro", "ドライブ BGM"),
}

# ── ジャンル別英語サブライン ──────────────────────────────────────────────
GENRE_EN_LINES: dict = {
    "lofi":      ("1 HOUR", "Chill Study Mix"),
    "edm":       ("1 HOUR", "Festival Energy Mix"),
    "ambient":   ("1 HOUR", "Deep Relaxation Mix"),
    "synthwave": ("1 HOUR", "Retro Night Drive Mix"),
}


def _gradient_bg(size: Tuple[int, int], c_top: tuple, c_bot: tuple) -> Image.Image:
    """縦方向グラデーション背景を生成する。"""
    w, h = size
    img = Image.new("RGB", size)
    for y in range(h):
        t = y / h
        r = int(c_top[0] * (1 - t) + c_bot[0] * t)
        g = int(c_top[1] * (1 - t) + c_bot[1] * t)
        b = int(c_top[2] * (1 - t) + c_bot[2] * t)
        for x in range(w):
            img.putpixel((x, y), (r, g, b))
    return img


def _add_film_grain(img: Image.Image, strength: int = 18) -> Image.Image:
    """フィルムグレインノイズを加算する (numpy なしの純 Pillow 実装)。"""
    import struct, random as rnd
    w, h = img.size
    pixels = img.load()
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            n = rnd.randint(-strength, strength)
            r, g, b = pixels[x, y]
            nr = max(0, min(255, r + n))
            ng = max(0, min(255, g + n))
            nb = max(0, min(255, b + n))
            for dy in range(2):
                for dx in range(2):
                    if x + dx < w and y + dy < h:
                        pixels[x + dx, y + dy] = (nr, ng, nb)
    return img


def _load_font(size: int) -> ImageFont.ImageFont:
    """システムフォントをロードする。失敗時は default フォント。"""
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _draw_glow_text(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    color: tuple,
    glow_color: tuple,
    glow_radius: int = 6,
) -> None:
    """テキストにグロー（ぼかし輝き）エフェクトをつけて描画する。"""
    # グロー用オーバーレイ
    tmp = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    for dx in range(-glow_radius, glow_radius + 1, 2):
        for dy in range(-glow_radius, glow_radius + 1, 2):
            tmp_draw.text((pos[0] + dx, pos[1] + dy), text, font=font,
                          fill=(*glow_color, 80))
    tmp = tmp.filter(ImageFilter.GaussianBlur(radius=glow_radius // 2))
    # メインレイヤーに合成
    draw._image.paste(Image.alpha_composite(
        draw._image.convert("RGBA"), tmp).convert("RGB"))
    # 本文
    draw.text(pos, text, font=font, fill=color)


def make_thumbnail(
    genre_slug: str,
    title: str,
    out_path: Path,
    duration_label: str = "1 HOUR MIX",
) -> Optional[Path]:
    """
    ジャンル別サムネイル (1280×720 JPEG) を生成して out_path に保存する。

    Args:
        genre_slug:     "lofi" | "edm" | "ambient" | "synthwave"
        title:          動画タイトル（英語短縮形）
        out_path:       出力先 Path (.jpg / .png)
        duration_label: 右上の時間表示

    Returns:
        生成されたファイルの Path。失敗時は None。
    """
    try:
        W, H = 1280, 720
        theme = GENRE_THEME.get(genre_slug, GENRE_THEME["lofi"])
        jp_main, jp_sub = GENRE_JP_LINES.get(genre_slug, ("BGM", "作業用"))
        en_dur,  en_sub = GENRE_EN_LINES.get(genre_slug, ("1 HOUR", "Music Mix"))

        # ── 背景グラデーション ──────────────────────────────────────────
        img = _gradient_bg((W, H), theme["bg_top"], theme["bg_bot"])

        # ── アクセントライン (水平) ──────────────────────────────────────
        draw = ImageDraw.Draw(img)
        ax, ay = 80, H // 2 - 10
        draw.rectangle([ax, ay, ax + 4, ay + 90], fill=theme["accent"])

        # ── フォント準備 ────────────────────────────────────────────────
        font_xl  = _load_font(82)   # メインタイトル
        font_lg  = _load_font(52)   # サブタイトル
        font_md  = _load_font(36)   # 英語小見出し
        font_sm  = _load_font(28)   # タグ / 時間

        # ── メインテキスト (JP) ─────────────────────────────────────────
        tx = 110
        draw.text((tx, H // 2 - 60), jp_main, font=font_xl, fill=theme["text_main"])
        draw.text((tx, H // 2 + 40), jp_sub,  font=font_lg, fill=theme["accent"])

        # ── 英語サブテキスト ────────────────────────────────────────────
        draw.text((tx, H // 2 + 105), en_sub, font=font_md, fill=theme["text_sub"])

        # ── 右上: 時間バッジ ────────────────────────────────────────────
        badge_x = W - 220
        draw.rectangle([badge_x, 30, W - 30, 90], fill=theme["accent"])
        draw.text((badge_x + 16, 38), en_dur, font=font_md, fill=(20, 20, 20))

        # ── 右下: ブランド名 ────────────────────────────────────────────
        brand_font = _load_font(24)
        draw.text((W - 210, H - 50), "All k Music", font=brand_font, fill=theme["text_sub"])

        # ── デコレーション：ランダムドット群 ────────────────────────────
        rng = random.Random(hash(genre_slug))
        for _ in range(60):
            dx = rng.randint(W // 2, W - 40)
            dy = rng.randint(40, H - 40)
            r  = rng.randint(1, 4)
            alpha = rng.randint(60, 160)
            ac = theme["accent"]
            draw.ellipse([dx - r, dy - r, dx + r, dy + r],
                         fill=(ac[0], ac[1], ac[2]))

        # ── フィルムグレイン ────────────────────────────────────────────
        img = _add_film_grain(img, strength=12)

        # ── 保存 ────────────────────────────────────────────────────────
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix.lower() in (".jpg", ".jpeg"):
            img.save(str(out_path), "JPEG", quality=95)
        else:
            img.save(str(out_path), "PNG")

        size_kb = out_path.stat().st_size // 1024
        logger.info("[Thumbnail] ✓ %s  (%d KB)", out_path.name, size_kb)
        return out_path

    except Exception as exc:
        logger.error("[Thumbnail] 生成失敗: %s", exc)
        return None
