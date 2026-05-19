"""
Thumbnail Maker — All k Music
────────────────────────────────────────────────────────────────────────
PIL/Pillow で 1280×720 JPG サムネイルを生成する。

スタイル:
  default   — グラデーション背景 + グロー文字 (従来スタイル)
  ncs       — 黒背景 + スペクトラムバー (NCS 風)
  lofi_girl — 夜の部屋イラスト + 窓 + ランプ (LoFi Girl 風)
"""

from __future__ import annotations

import logging
import math
import random
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# ── ジャンル別カラーテーマ (default スタイル) ────────────────────────────────
GENRE_THEME: dict = {
    "lofi": {
        "bg_top":    (28,  24,  38),
        "bg_bot":    (18,  30,  40),
        "accent":    (255, 200, 100),
        "text_main": (240, 230, 200),
        "text_sub":  (180, 170, 155),
        "glow":      (255, 180,  80),
    },
    "edm": {
        "bg_top":    (10,   5,  30),
        "bg_bot":    (30,   5,  50),
        "accent":    (0,  230, 255),
        "text_main": (220, 240, 255),
        "text_sub":  (130, 200, 255),
        "glow":      (80,  200, 255),
    },
    "ambient": {
        "bg_top":    (5,   20,  30),
        "bg_bot":    (10,  10,  25),
        "accent":    (100, 220, 180),
        "text_main": (200, 235, 220),
        "text_sub":  (130, 190, 170),
        "glow":      (80,  200, 160),
    },
    "synthwave": {
        "bg_top":    (15,   5,  35),
        "bg_bot":    (35,   5,  25),
        "accent":    (255,  80, 200),
        "text_main": (255, 220, 240),
        "text_sub":  (200, 150, 220),
        "glow":      (255,  60, 180),
    },
}

GENRE_JP_LINES: dict = {
    "lofi":      ("Lo-fi Hip Hop", "作業用 BGM"),
    "edm":       ("EDM Glitch Hop", "フェス系 BGM"),
    "ambient":   ("Ambient Healing", "睡眠・瞑想 BGM"),
    "synthwave": ("Synthwave Retro", "ドライブ BGM"),
}

GENRE_EN_LINES: dict = {
    "lofi":      ("1 HOUR", "Chill Study Mix"),
    "edm":       ("1 HOUR", "Festival Energy Mix"),
    "ambient":   ("1 HOUR", "Deep Relaxation Mix"),
    "synthwave": ("1 HOUR", "Retro Night Drive Mix"),
}

# ── NCS スタイルパラメータ ────────────────────────────────────────────────────
_NCS_THUMB: dict = {
    "lofi":      {"accent": (255, 166,  26), "label": "Lo-fi Hip Hop  |  1 Hour Study Mix",    "bg": (13, 13, 13)},
    "edm":       {"accent": (  0, 229, 255), "label": "EDM  |  1 Hour Festival Energy Mix",     "bg": ( 5,  0, 10)},
    "ambient":   {"accent": ( 89, 230, 160), "label": "Ambient  |  1 Hour Deep Relaxation Mix", "bg": ( 2, 10, 15)},
    "synthwave": {"accent": (255,  77, 204), "label": "Synthwave  |  1 Hour Night Drive Mix",   "bg": (15,  5, 35)},
}

# ── LoFi Girl スタイルパラメータ ──────────────────────────────────────────────
_LOFI_THUMB: dict = {
    "lofi":      {"accent": (255, 215,   0), "city": (40, 50, 80),  "lamp": (255, 180,  80)},
    "edm":       {"accent": (  0, 229, 255), "city": (20, 10, 60),  "lamp": (100, 200, 255)},
    "ambient":   {"accent": (127, 255, 212), "city": (10, 30, 40),  "lamp": (150, 230, 200)},
    "synthwave": {"accent": (255, 105, 180), "city": (50, 10, 60),  "lamp": (255, 100, 200)},
}


# ─────────────────────────────────────────────────────────────────────────────
# 共通ヘルパー
# ─────────────────────────────────────────────────────────────────────────────

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
    import random as rnd
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
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/System/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
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
    tmp = Image.new("RGBA", draw._image.size, (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    for dx in range(-glow_radius, glow_radius + 1, 2):
        for dy in range(-glow_radius, glow_radius + 1, 2):
            tmp_draw.text((pos[0] + dx, pos[1] + dy), text, font=font,
                          fill=(*glow_color, 80))
    tmp = tmp.filter(ImageFilter.GaussianBlur(radius=glow_radius // 2))
    draw._image.paste(Image.alpha_composite(
        draw._image.convert("RGBA"), tmp).convert("RGB"))
    draw.text(pos, text, font=font, fill=color)


def _save_image(img: Image.Image, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        img.save(str(out_path), "JPEG", quality=95)
    else:
        img.save(str(out_path), "PNG")


# ─────────────────────────────────────────────────────────────────────────────
# NCS スタイル
# ─────────────────────────────────────────────────────────────────────────────

def _make_ncs_thumbnail(genre_slug: str, out_path: Path) -> Optional[Path]:
    """NCS 風サムネイル: 黒背景 + EQ スペクトラムバー + テキスト (1280×720)。"""
    try:
        W, H = 1280, 720
        p = _NCS_THUMB.get(genre_slug, _NCS_THUMB["lofi"])
        accent = p["accent"]
        bg     = p["bg"]
        label  = p["label"]

        img  = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)

        # ── スペクトラムバー (右 55%) ────────────────────────────────────
        rng = random.Random(hash(genre_slug + "_ncs"))
        bar_x0   = int(W * 0.44)
        bar_count = 64
        bar_w    = (W - bar_x0 - 20) // bar_count
        max_h    = int(H * 0.78)

        for i in range(bar_count):
            env   = math.sin(math.pi * i / bar_count)          # envelope
            noise = rng.uniform(0.55, 1.0)
            bh    = int(max_h * (0.15 + 0.85 * env * noise))
            bx    = bar_x0 + i * bar_w
            by    = H - 58 - bh
            bright = 0.35 + 0.65 * env * noise
            col = tuple(min(255, int(c * bright)) for c in accent)
            draw.rectangle([bx, by, bx + bar_w - 2, H - 58], fill=col)

        # ── 左フェードオーバーレイ ────────────────────────────────────────
        fade_end = int(W * 0.64)
        overlay  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ov_draw  = ImageDraw.Draw(overlay)
        for x in range(fade_end):
            alpha = int(240 * (1 - x / fade_end) ** 1.5)
            ov_draw.line([(x, 0), (x, H)], fill=(*bg, alpha))
        img  = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # ── アクセントライン (バー下端) ──────────────────────────────────
        draw.rectangle([bar_x0, H - 61, W, H - 57], fill=accent)

        # ── 左: 縦アクセントバー ─────────────────────────────────────────
        draw.rectangle([72, H // 2 - 95, 79, H // 2 + 65], fill=accent)

        # ── テキスト ─────────────────────────────────────────────────────
        font_brand = _load_font(72)
        font_label = _load_font(34)
        font_badge = _load_font(24)

        tx = 102
        draw.text((tx, H // 2 - 95), "ALL K MUSIC", font=font_brand, fill=(255, 255, 255))
        draw.text((tx, H // 2 + 14), label, font=font_label, fill=accent)

        # 右上バッジ
        bw = 200
        draw.rectangle([W - bw - 22, 22, W - 22, 72], fill=accent)
        draw.text((W - bw - 6, 29), "1 HOUR MIX", font=font_badge, fill=(10, 10, 10))

        img = _add_film_grain(img, strength=7)
        _save_image(img, out_path)
        logger.info("[Thumbnail/NCS] ✓ %s", out_path.name)
        return out_path

    except Exception as exc:
        logger.error("[Thumbnail/NCS] 生成失敗: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# LoFi Girl スタイル
# ─────────────────────────────────────────────────────────────────────────────

def _make_lofi_girl_thumbnail(
    genre_slug: str,
    out_path: Path,
    size: Tuple[int, int] = (1280, 720),
) -> Optional[Path]:
    """
    LoFi Girl 風サムネイル/背景: 夜の部屋 + 窓 + デスクランプ + シルエット。
    size=(1280,720) でサムネイル、size=(1920,1080) で動画背景として使用。
    """
    try:
        W, H = size
        sx = W / 1280   # 水平スケール
        sy = H / 720    # 垂直スケール

        def px(x: float) -> int: return int(x * sx)
        def py(y: float) -> int: return int(y * sy)

        p       = _LOFI_THUMB.get(genre_slug, _LOFI_THUMB["lofi"])
        accent  = p["accent"]
        city_c  = p["city"]
        lamp_c  = p["lamp"]

        # ── 背景: 深夜ネイビー ───────────────────────────────────────────
        img  = _gradient_bg((W, H), (12, 14, 28), (8, 8, 18))
        draw = ImageDraw.Draw(img)

        # ── 天井・壁 (上 1/3) ────────────────────────────────────────────
        draw.rectangle([0, 0, W, py(240)], fill=(18, 20, 35))

        # ── 窓 (右寄り) ───────────────────────────────────────────────────
        wx0 = px(560)
        wy0 = py(55)
        wx1 = px(1230)
        wy1 = py(520)
        ww  = wx1 - wx0
        wh  = wy1 - wy0

        # 窓の外の夜景
        sky  = Image.new("RGB", (ww, wh), city_c)
        sd   = ImageDraw.Draw(sky)

        # 夜空グラデーション (上ほど暗い)
        for y in range(wh):
            t   = y / wh
            r   = int(city_c[0] * (0.6 + 0.4 * t))
            g   = int(city_c[1] * (0.6 + 0.4 * t))
            b   = int(city_c[2] * (0.6 + 0.4 * t))
            sd.line([(0, y), (ww, y)], fill=(r, g, b))

        # ビルのシルエット
        rng  = random.Random(hash(genre_slug + "_city"))
        bx   = 0
        while bx < ww:
            bld_w = rng.randint(px(40), px(100))
            bld_h = rng.randint(py(100), py(300))
            bld_y = wh - bld_h
            bld_col = (
                max(0, city_c[0] - 8),
                max(0, city_c[1] - 8),
                max(0, city_c[2] - 5),
            )
            sd.rectangle([bx, bld_y, bx + bld_w, wh], fill=bld_col)
            # 窓ライト
            for _ in range(rng.randint(2, 8)):
                lx = rng.randint(bx + 4, bx + bld_w - 4)
                ly = rng.randint(bld_y + 4, wh - 10)
                br = rng.randint(140, 255)
                wr = rng.randint(3, 7)
                wh2 = rng.randint(3, 5)
                w_col = (
                    min(255, city_c[0] + br),
                    min(255, city_c[1] + br // 2),
                    min(255, city_c[2] + br // 3),
                )
                sd.rectangle([lx, ly, lx + wr, ly + wh2], fill=w_col)
            bx += bld_w + rng.randint(0, px(15))

        # 雨の線 (窓ガラス)
        for _ in range(100):
            rx = rng.randint(0, ww)
            ry = rng.randint(0, wh)
            rl = rng.randint(py(6), py(18))
            sd.line([(rx, ry), (rx - 1, ry + rl)], fill=(160, 180, 210), width=1)

        img.paste(sky, (wx0, wy0))
        draw = ImageDraw.Draw(img)

        # 窓枠
        fw = max(5, px(7))
        fc = (55, 50, 65)
        draw.rectangle([wx0 - fw, wy0 - fw, wx1 + fw, wy1 + fw], outline=fc, width=fw)
        # 窓の縦横クロスバー
        draw.line([(wx0 + ww // 2, wy0), (wx0 + ww // 2, wy1)], fill=fc, width=fw)
        draw.line([(wx0, wy0 + wh * 2 // 5), (wx1, wy0 + wh * 2 // 5)], fill=fc, width=fw)

        # ── 床・デスク面 ─────────────────────────────────────────────────
        desk_y = py(518)
        draw.rectangle([0, desk_y, W, H], fill=(20, 15, 25))
        draw.line([(0, desk_y), (W, desk_y)], fill=(45, 38, 55), width=2)

        # ── ランプグロー ──────────────────────────────────────────────────
        lamp_cx = px(430)
        lamp_cy = py(420)
        glow_ov  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd       = ImageDraw.Draw(glow_ov)
        for radius in range(py(160), 0, -py(8)):
            t   = 1 - radius / py(160)
            alp = int(55 * t * t)
            gd.ellipse(
                [lamp_cx - radius, lamp_cy - radius,
                 lamp_cx + radius, lamp_cy + radius],
                fill=(*lamp_c, alp),
            )
        img  = Image.alpha_composite(img.convert("RGBA"), glow_ov).convert("RGB")
        draw = ImageDraw.Draw(img)

        # ランプ本体 (ポール + シェード)
        pole_x = px(440)
        draw.line([(pole_x, desk_y), (pole_x, py(370))], fill=(60, 55, 70), width=max(3, px(5)))
        arm_y  = py(375)
        draw.line([(pole_x, arm_y), (px(410), arm_y - py(25))], fill=(60, 55, 70), width=max(2, px(4)))
        shade_cx = px(405)
        shade_y  = arm_y - py(25)
        draw.polygon([
            (shade_cx - px(28), shade_y + py(4)),
            (shade_cx + px(28), shade_y + py(4)),
            (shade_cx + px(16), shade_y - py(32)),
            (shade_cx - px(16), shade_y - py(32)),
        ], fill=(85, 75, 65))
        draw.ellipse([shade_cx - px(5), shade_y + py(1),
                      shade_cx + px(5), shade_y + py(10)], fill=lamp_c)

        # ── 猫シルエット (窓辺) ──────────────────────────────────────────
        cat_x = wx0 + ww * 2 // 5
        cat_y = wy1 + py(2)
        dark  = (6, 6, 16)
        # 胴体
        draw.ellipse([cat_x - px(15), cat_y - py(28), cat_x + px(15), cat_y], fill=dark)
        # 頭
        draw.ellipse([cat_x - px(12), cat_y - py(46), cat_x + px(12), cat_y - py(22)], fill=dark)
        # 耳
        draw.polygon([(cat_x - px(12), cat_y - py(44)),
                      (cat_x - px(5),  cat_y - py(60)),
                      (cat_x - px(1),  cat_y - py(44))], fill=dark)
        draw.polygon([(cat_x + px(1),  cat_y - py(44)),
                      (cat_x + px(5),  cat_y - py(60)),
                      (cat_x + px(12), cat_y - py(44))], fill=dark)
        # しっぽ
        draw.line([(cat_x + px(15), cat_y - py(5)),
                   (cat_x + px(38), cat_y - py(22)),
                   (cat_x + px(44), cat_y - py(10))],
                  fill=dark, width=max(3, px(5)))

        # ── キャラクターシルエット (デスクで作業中) ─────────────────────
        ch_x = px(500)
        ch_y = desk_y
        # 上半身
        draw.rectangle([ch_x - px(22), ch_y - py(85), ch_x + px(22), ch_y - py(18)], fill=dark)
        # 頭
        draw.ellipse([ch_x - px(20), ch_y - py(128), ch_x + px(20), ch_y - py(85)], fill=dark)
        # 髪
        draw.rectangle([ch_x - px(20), ch_y - py(128), ch_x + px(20), ch_y - py(108)], fill=dark)
        draw.polygon([(ch_x + px(16), ch_y - py(128)),
                      (ch_x + px(32), ch_y - py(95)),
                      (ch_x + px(22), ch_y - py(95))], fill=dark)
        # 腕 (本・画面に向かっている)
        draw.line([(ch_x + px(22), ch_y - py(60)),
                   (ch_x + px(55), ch_y - py(22))], fill=dark, width=max(6, px(10)))

        # ── 左側テキスト ─────────────────────────────────────────────────
        tx    = px(55)
        ty    = py(165)
        f_ttl = _load_font(int(48 * min(sx, sy)))
        f_gen = _load_font(int(31 * min(sx, sy)))
        f_sub = _load_font(int(22 * min(sx, sy)))
        f_tag = _load_font(int(17 * min(sx, sy)))

        # 縦アクセントバー
        draw.rectangle([tx - px(12), ty, tx - px(5), ty + py(125)], fill=accent)

        draw.text((tx, ty),              "All k Music",                          font=f_ttl, fill=(230, 225, 210))
        draw.text((tx, ty + py(57)),     GENRE_JP_LINES.get(genre_slug, ("BGM", ""))[0], font=f_gen, fill=accent)
        draw.text((tx, ty + py(96)),     GENRE_EN_LINES.get(genre_slug, ("1 HOUR", "Mix"))[1], font=f_sub, fill=(155, 145, 135))
        draw.text((tx, H - py(42)),      "lofi • study • chill",                font=f_tag, fill=(90, 80, 72))

        img = _add_film_grain(img, strength=13)
        _save_image(img, out_path)
        logger.info("[Thumbnail/LoFi] ✓ %s  (%dx%d)", out_path.name, W, H)
        return out_path

    except Exception as exc:
        logger.error("[Thumbnail/LoFi] 生成失敗: %s", exc)
        return None


def make_lofi_girl_bg(genre_slug: str, out_path: Path) -> Optional[Path]:
    """LoFi Girl 風動画背景 (1920×1080 PNG) を生成して out_path に保存する。"""
    return _make_lofi_girl_thumbnail(genre_slug, out_path, size=(1920, 1080))


# ─────────────────────────────────────────────────────────────────────────────
# デフォルトスタイル
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(
    genre_slug: str,
    title: str,
    out_path: Path,
    duration_label: str = "1 HOUR MIX",
    style: str = "default",
) -> Optional[Path]:
    """
    ジャンル別サムネイル (1280×720 JPEG) を生成して out_path に保存する。

    Args:
        genre_slug:     "lofi" | "edm" | "ambient" | "synthwave"
        title:          動画タイトル（英語短縮形）
        out_path:       出力先 Path (.jpg / .png)
        duration_label: 右上の時間表示 (default スタイルのみ)
        style:          "default" | "ncs" | "lofi_girl"

    Returns:
        生成されたファイルの Path。失敗時は None。
    """
    if style == "ncs":
        return _make_ncs_thumbnail(genre_slug, out_path)
    if style == "lofi_girl":
        return _make_lofi_girl_thumbnail(genre_slug, out_path)

    # ── デフォルトスタイル ───────────────────────────────────────────────
    try:
        W, H = 1280, 720
        theme    = GENRE_THEME.get(genre_slug, GENRE_THEME["lofi"])
        jp_main, jp_sub = GENRE_JP_LINES.get(genre_slug, ("BGM", "作業用"))
        en_dur,  en_sub = GENRE_EN_LINES.get(genre_slug, ("1 HOUR", "Music Mix"))

        img  = _gradient_bg((W, H), theme["bg_top"], theme["bg_bot"])
        draw = ImageDraw.Draw(img)

        # アクセントライン (縦)
        ax, ay = 80, H // 2 - 10
        draw.rectangle([ax, ay, ax + 4, ay + 90], fill=theme["accent"])

        font_xl  = _load_font(82)
        font_lg  = _load_font(52)
        font_md  = _load_font(36)
        font_sm  = _load_font(28)

        tx = 110
        draw.text((tx, H // 2 - 60), jp_main, font=font_xl, fill=theme["text_main"])
        draw.text((tx, H // 2 + 40), jp_sub,  font=font_lg, fill=theme["accent"])
        draw.text((tx, H // 2 + 105), en_sub, font=font_md, fill=theme["text_sub"])

        badge_x = W - 220
        draw.rectangle([badge_x, 30, W - 30, 90], fill=theme["accent"])
        draw.text((badge_x + 16, 38), en_dur, font=font_md, fill=(20, 20, 20))

        brand_font = _load_font(24)
        draw.text((W - 210, H - 50), "All k Music", font=brand_font, fill=theme["text_sub"])

        rng = random.Random(hash(genre_slug))
        for _ in range(60):
            dx  = rng.randint(W // 2, W - 40)
            dy  = rng.randint(40, H - 40)
            r   = rng.randint(1, 4)
            ac  = theme["accent"]
            draw.ellipse([dx - r, dy - r, dx + r, dy + r], fill=(ac[0], ac[1], ac[2]))

        img = _add_film_grain(img, strength=12)

        _save_image(img, out_path)
        size_kb = out_path.stat().st_size // 1024
        logger.info("[Thumbnail] ✓ %s  (%d KB)", out_path.name, size_kb)
        return out_path

    except Exception as exc:
        logger.error("[Thumbnail] 生成失敗: %s", exc)
        return None
