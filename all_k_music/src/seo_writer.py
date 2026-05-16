"""
SEO Writer — All k Music
────────────────────────────────────────────────────────────────────────
YouTube 動画説明欄・ハッシュタグ・タイトルを日本語 + 英語の多言語で
自動生成する。

出力形式:
  ① 動画タイトル (JP / EN)
  ② 概要欄本文 (JP + EN ブロック)
     - チャプタースタンプ (00:00, 07:30, 15:00 … )
     - ジャンル別 CTA
     - All k Music ブランドライン
  ③ ハッシュタグ (30 タグ上限)

Gemini 拡張 (オプション):
  GEMINI_API_KEY が設定されている場合、Gemini でコピーライティングを
  強化する。未設定の場合はテンプレートモードで動作する。
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── All k Music チャンネル定数 ──────────────────────────────────────────
CHANNEL_ID  = "UCivGmZbFU4qugFr7O-RlJCw"
CHANNEL_URL = f"https://www.youtube.com/channel/{CHANNEL_ID}"
CHANNEL_NAME = "All k Music"

# ── ジャンル別テンプレートデータ ─────────────────────────────────────────
_GENRE_DATA: dict = {
    "lofi": {
        "title_jp": "【1時間】Lo-fi Hip Hop 作業用BGM | 勉強・集中・深夜作業",
        "title_en": "1 Hour Lo-fi Hip Hop | Study & Focus BGM Mix",
        "description_jp": (
            "🎧 Lo-fi Hip Hop の神繋ぎメドレー。\n"
            "勉強・テスト前・深夜の作業や読書のお供にどうぞ。\n"
            "ビニールノイズと温かいコードが脳をリラックスモードへ導きます。"
        ),
        "description_en": (
            "🎧 A seamless 1-hour Lo-fi Hip Hop medley.\n"
            "Perfect for studying, late-night work, or just chilling.\n"
            "Warm vinyl textures and jazzy chords to keep you in the zone."
        ),
        "cta_jp": "▶ 勉強・作業中にリピート再生してください ♪",
        "cta_en": "▶ Loop it while you study or work ♪",
        "hashtags": [
            "#lofi", "#lofihiphop", "#作業用BGM", "#勉強用BGM", "#集中BGM",
            "#深夜作業", "#lofimusic", "#chillbeats", "#studymusic",
            "#lofichill", "#BGM", "#作業BGM", "#1時間BGM", "#lofi作業",
            "#AllkMusic",
        ],
    },
    "edm": {
        "title_jp": "【1時間】EDM Glitch Hop | フェス系アゲアゲBGM Mix",
        "title_en": "1 Hour EDM Glitch Hop | Festival Energy Mix",
        "description_jp": (
            "⚡ EDMドロップが連続する神繋ぎメドレー。\n"
            "トレーニング・ドライブ・テンションを上げたい時に最適。\n"
            "ハードドロップと残響エコーが気分を最高潮に引き上げます。"
        ),
        "description_en": (
            "⚡ Non-stop EDM drops — glitch hop, melodic dubstep, and more.\n"
            "Perfect for workouts, driving, or hyping yourself up.\n"
            "Echo-drenched transitions keep the energy at festival level."
        ),
        "cta_jp": "▶ トレーニング・ドライブのお供に ♪",
        "cta_en": "▶ Crank it up during your workout or drive ♪",
        "hashtags": [
            "#EDM", "#glitchhop", "#フェスBGM", "#トレーニングBGM", "#ドライブBGM",
            "#workoutmusic", "#edmmusic", "#festivalmusic", "#電子音楽",
            "#ダンスミュージック", "#テンション上がる曲", "#1時間EDM",
            "#edmhiphop", "#melodicdubstep", "#AllkMusic",
        ],
    },
    "ambient": {
        "title_jp": "【1時間】Ambient Healing | 睡眠・瞑想・リラックスBGM",
        "title_en": "1 Hour Ambient Healing | Sleep · Meditation · Relaxation BGM",
        "description_jp": (
            "🌊 ディープアンビエントの超スムーズフェードメドレー。\n"
            "睡眠導入・瞑想・ヨガ・ストレス解消に。\n"
            "528Hzヒーリング周波数で心と体をリセットしてください。"
        ),
        "description_en": (
            "🌊 Ultra-smooth ambient healing medley with deep crossfades.\n"
            "Ideal for sleep, meditation, yoga, and stress relief.\n"
            "528Hz healing frequencies to reset your mind and body."
        ),
        "cta_jp": "▶ 就寝前や瞑想中に流してください ♪",
        "cta_en": "▶ Let it play as you fall asleep or meditate ♪",
        "hashtags": [
            "#ambient", "#睡眠BGM", "#瞑想BGM", "#ヒーリングミュージック",
            "#リラックスBGM", "#528Hz", "#sleepmusic", "#meditationmusic",
            "#healingmusic", "#ambientmusic", "#ヨガBGM", "#スリープミュージック",
            "#深呼吸", "#ストレス解消", "#AllkMusic",
        ],
    },
    "synthwave": {
        "title_jp": "【1時間】Synthwave Retro | 夜ドライブ・レトロフューチャーBGM",
        "title_en": "1 Hour Synthwave Retro | Night Drive · Retro Future BGM Mix",
        "description_jp": (
            "🌃 80年代レトロフューチャーのシンセウェーブメドレー。\n"
            "夜ドライブ・夜更かし・クリエイティブ作業のBGMに。\n"
            "テープ感のあるフェードとアナログシンセの音色がノスタルジーを呼び起こします。"
        ),
        "description_en": (
            "🌃 80s retro-future synthwave medley with tape-saturated fades.\n"
            "Perfect for night drives, late nights, and creative work.\n"
            "Analog polysynths and pulsing basslines bring the neon city to life."
        ),
        "cta_jp": "▶ 夜のドライブや作業BGMに ♪",
        "cta_en": "▶ Soundtrack your night drive or creative session ♪",
        "hashtags": [
            "#synthwave", "#レトロフューチャー", "#夜ドライブBGM", "#シンセウェーブ",
            "#retrowave", "#夜更かしBGM", "#outrun", "#synthwavemusic",
            "#80smusic", "#ネオン", "#cyberpunk", "#vapourwave",
            "#ドライブBGM", "#クリエイター作業BGM", "#AllkMusic",
        ],
    },
}

# ── チャプタースタンプ生成 ──────────────────────────────────────────────
def _build_chapters(
    num_segments: int = 8,
    segment_sec: int = 450,
    genre_slug: str = "lofi",
) -> str:
    """
    チャプタースタンプ文字列を生成する。
    例: 00:00 ♪ Track 1 / 07:30 ♪ Track 2 …
    """
    label_suffix = _GENRE_DATA.get(genre_slug, _GENRE_DATA["lofi"])["title_jp"].split("】")[-1].strip()
    lines = []
    for i in range(num_segments):
        total_sec = i * segment_sec
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        ts = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        lines.append(f"{ts} ♪ Track {i + 1}")
    return "\n".join(lines)


def _gemini_enhance(base_description: str, genre_slug: str) -> str:
    """
    Gemini でコピーライティングを強化する (オプション)。
    GEMINI_API_KEY が未設定の場合はベース説明文をそのまま返す。
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.debug("[SEOWriter] GEMINI_API_KEY 未設定 — テンプレートモードで動作")
        return base_description

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            f"次の YouTube 動画説明欄を、SEO を意識した魅力的な日本語・英語混合コピーに"
            f"リライトしてください。ジャンル: {genre_slug}。"
            f"元の内容から逸脱せず、自然検索で上位表示されやすいキーワードを追加してください。\n\n"
            f"---\n{base_description}\n---\n\n"
            f"リライト後の説明欄のみ出力してください（前置き不要）。"
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        enhanced = resp.text.strip()
        logger.info("[SEOWriter] Gemini でコピーを強化しました (%d chars)", len(enhanced))
        return enhanced
    except Exception as exc:
        logger.warning("[SEOWriter] Gemini 強化失敗 — テンプレートを使用: %s", exc)
        return base_description


def generate_seo_package(
    genre_slug: str,
    asset_id: str,
    use_gemini: bool = True,
    num_segments: int = 8,
    segment_sec: int = 450,
) -> dict:
    """
    YouTube SEO パッケージを生成する。

    Args:
        genre_slug:   "lofi" | "edm" | "ambient" | "synthwave"
        asset_id:     "20260516-001" 形式のアセット ID
        use_gemini:   True = Gemini でコピー強化を試みる
        num_segments: メドレーのセグメント数 (チャプター数)
        segment_sec:  1 セグメントの秒数

    Returns:
        {
            "title_jp": str,
            "title_en": str,
            "description": str,   # YouTube 概要欄全文
            "hashtags": List[str],
            "tags_str": str,      # カンマ区切りタグ (YouTube タグ欄用)
        }
    """
    data = _GENRE_DATA.get(genre_slug, _GENRE_DATA["lofi"])

    chapters = _build_chapters(num_segments, segment_sec, genre_slug)

    base_desc = (
        f"{data['description_jp']}\n\n"
        f"{data['description_en']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎵 CHAPTERS\n"
        f"{chapters}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{data['cta_jp']}\n"
        f"{data['cta_en']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 {CHANNEL_NAME}\n"
        f"チャンネル登録して通知をオンにすると、毎日新しいBGMが届きます ✔\n"
        f"Subscribe & hit the 🔔 to get daily BGM drops.\n"
        f"→ {CHANNEL_URL}\n\n"
        f"Asset ID: {asset_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    description = _gemini_enhance(base_desc, genre_slug) if use_gemini else base_desc

    hashtags = data["hashtags"]
    tags_str = ", ".join(t.lstrip("#") for t in hashtags)

    return {
        "title_jp":   data["title_jp"],
        "title_en":   data["title_en"],
        "description": description,
        "hashtags":   hashtags,
        "tags_str":   tags_str,
    }


def save_seo_txt(seo: dict, out_path: "Path") -> None:
    """SEO パッケージをテキストファイルに保存する。"""
    lines = [
        "═" * 60,
        f"TITLE (JP): {seo['title_jp']}",
        f"TITLE (EN): {seo['title_en']}",
        "═" * 60,
        "DESCRIPTION:",
        seo["description"],
        "═" * 60,
        "HASHTAGS:",
        " ".join(seo["hashtags"]),
        "═" * 60,
        "TAGS (comma-separated):",
        seo["tags_str"],
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("[SEOWriter] ✓ %s", out_path.name)
