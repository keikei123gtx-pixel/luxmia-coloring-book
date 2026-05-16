"""
Trend Curator — All k Music
────────────────────────────────────────────────────────────────────────
4ジャンルの GenreProfile を管理し、Suno AI 向け高品質スタイルプロンプトを
セッションごとにランダムに組み合わせて生成する。

【商用利用安全ロジック (2026年対応)】
  ① 特定アーティスト名・著作権付きIP名を全タグから排除済み
     ("TheFatRat", "Blade Runner", "Miami Vice", etc.)
  ② _BANNED_KEYWORDS でプロンプトをバリデーション — リミックス/拡張系を完全ブロック
  ③ make_instrumental=True を全ジャンルで強制
  ④ continue_clip_id, extend, remix を API ペイロードから完全排除
  ⑤ curate_session() の返り値に generation_seed を付与
     → asset_vault.py でフィンガープリントを生成する際に使用
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from typing import List

from src.asset_vault import generate_seed

logger = logging.getLogger(__name__)

# ── 商用利用NGキーワード (プロンプトに混入した場合は自動除去 + 警告) ─────────
_BANNED_KEYWORDS: List[str] = [
    # アーティスト名パターン
    "thefatrat", "marshmello", "skrillex", "deadmau5", "daft punk",
    "aphex twin", "burial", "boards of canada", "nujabes",
    "j dilla", "madlib", "9th wonder",
    # 著作権付きIP / ブランド
    "blade runner", "miami vice", "stranger things", "tron",
    "star wars", "inception", "interstellar",
    # リミックス / 拡張系フラグワード
    "remix", "remixed", "extend", "extension", "continue",
    "based on", "inspired by", "in the style of", "sounds like",
    "cover", "tribute", "interpolation", "sample of",
    # Suno API 危険操作ワード
    "continue_clip", "seed song", "extend song",
]

# ── アーティスト名を検出するための正規表現 ──────────────────────────────────
_ARTIST_RE = re.compile(
    r"\b(thefatrat|marshmello|skrillex|deadmau5|daft\s+punk|aphex\s+twin"
    r"|burial|nujabes|j\s+dilla|madlib)\b",
    re.IGNORECASE,
)


def _validate_prompt_safety(prompt_text: str) -> tuple[bool, List[str]]:
    """
    プロンプトに商用NGキーワードが含まれていないかチェックする。
    単語境界 (\b) を使用して部分一致の誤検知を防ぐ。

    Returns:
        (is_safe, found_violations)
    """
    violations = []
    for kw in _BANNED_KEYWORDS:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, prompt_text, re.IGNORECASE):
            violations.append(kw)
    return (len(violations) == 0), violations


def _sanitize_prompt(prompt_text: str) -> str:
    """
    商用NGキーワードをプロンプトから除去して返す。
    アーティスト名は空文字に置換。
    """
    sanitized = _ARTIST_RE.sub("", prompt_text)
    for kw in _BANNED_KEYWORDS:
        pattern = r"\b" + re.escape(kw) + r"\b"
        sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)
    # 複数スペース・先頭末尾スペースを整理
    sanitized = re.sub(r"\s{2,}", " ", sanitized).strip().strip(",").strip()
    return sanitized


@dataclass
class GenreProfile:
    """1つのジャンルに対応するプロファイル。"""

    name: str
    slug: str
    bpm: int
    style_tags: List[str]
    negative_tags: List[str] = field(default_factory=list)
    make_instrumental: bool = True  # 常に True — ボーカル入り生成を禁止

    def build_prompt(self, n_tags: int = 4, seed: int = 0) -> str:
        """
        style_tags から n_tags 個選んでカンマ区切りプロンプトを生成する。
        seed を渡すと再現可能な選択になる。
        各タグは商用安全チェックを通過したものだけを使用。
        """
        rng = random.Random(seed) if seed else random
        selected = rng.sample(self.style_tags, min(n_tags, len(self.style_tags)))
        prompt = ", ".join(selected)

        # 安全チェック & サニタイズ
        is_safe, violations = _validate_prompt_safety(prompt)
        if not is_safe:
            logger.warning(
                "[TrendCurator] NG キーワード検出 (%s): %s → 自動除去します",
                self.slug, violations,
            )
            prompt = _sanitize_prompt(prompt)

        return prompt

    def build_negative(self) -> str:
        return ", ".join(self.negative_tags)


class TrendCurator:
    """
    4つのコアジャンルを管理し、セッション用プロンプトを生成するエージェント。

    【2026年商用安全ポリシー】
    - 全タグはアーティスト名・著作権IP を含まない記述的表現のみ
    - make_instrumental=True を全ジャンルで強制
    - continue_clip_id / extend / remix 系パラメータは一切出力しない
    - 各プロンプトに固有 generation_seed を付与 (証拠台帳との連携用)
    """

    GENRES: List[GenreProfile] = [
        # ① Lo-fi Hip Hop — 90 BPM
        GenreProfile(
            name="Lo-fi Hip Hop",
            slug="lofi",
            bpm=90,
            style_tags=[
                "chill lofi beats",
                "vinyl crackle texture",
                "nostalgic dusty piano",
                "jazzy chord progressions",
                "warm muffled bass",
                "lo-fi drum breaks",
                "tape saturation",
                "rainy window ambience",
                "cozy late night studying",
                "boom bap influenced",
                "soft Rhodes electric piano",
                "city rain background noise",
                "mellow introspective mood",
                "vintage sample chop",
                "lo-fi aesthetic bedroom pop",
            ],
            negative_tags=[
                "vocals", "lyrics", "singing", "bright synths",
                "club music", "fast tempo",
            ],
        ),

        # ② EDM / Glitch Hop — 140 BPM
        # 注: 特定アーティスト名を排除し、音楽的特徴の記述に置換済み
        GenreProfile(
            name="EDM Glitch Hop",
            slug="edm",
            bpm=140,
            style_tags=[
                "uplifting melodic instrumental EDM",
                "glitch hop electronic",
                "massive festival drop",
                "euphoric saw wave leads",
                "sidechained pumping bass",
                "arpeggiated synth melody",
                "four-on-the-floor kick drum",
                "future bass wobble",
                "orchestral EDM buildup",
                "melodic dubstep",
                "catchy main hook",
                "energetic crowd pleaser",
                "cinematic electronic intro",
                "epic synth breakdown",
                "glitchy digital stutter",
            ],
            negative_tags=[
                "slow tempo", "acoustic instruments only",
                "folk", "jazz", "ambient",
            ],
        ),

        # ③ Ambient Healing — 60 BPM / 528 Hz
        GenreProfile(
            name="Ambient Healing",
            slug="ambient",
            bpm=60,
            style_tags=[
                "healing ambient 528Hz frequency",
                "deep relaxation soundscape",
                "meditation drone pads",
                "crystal singing bowl resonance",
                "theta wave binaural beats",
                "oceanic tidal waves",
                "forest bird ambience",
                "soft rain on leaves",
                "spa relaxation music",
                "floating ethereal atmosphere",
                "sleep aid music",
                "spiritual inner peace",
                "slow evolving textures",
                "sacred geometry sound",
                "chakra balancing tones",
            ],
            negative_tags=[
                "drums", "percussion", "beat", "fast",
                "energetic", "vocals", "distortion",
            ],
        ),

        # ④ Synthwave Retro — 118 BPM
        # 注: "Blade Runner", "Miami Vice" 等の著作権IPを記述的表現に置換済み
        GenreProfile(
            name="Synthwave Retro",
            slug="synthwave",
            bpm=118,
            style_tags=[
                "80s synthwave retro futurism",
                "outrun driving night highway",
                "neon city nightscape aesthetic",
                "dark cinematic retro electronic score",
                "analog polysynth chords",
                "gated reverb drum machine",
                "catchy retrowave melody",
                "dark cinematic synthwave",
                "electric guitar solo 80s",
                "vaporwave nostalgia",
                "pulsing bassline arpeggio",
                "chromatic FM synth leads",
                "classic analog polysynth sound",
                "glamorous 80s sunset driving atmosphere",
                "cyberpunk dystopia score",
            ],
            negative_tags=[
                "acoustic only", "folk", "jazz",
                "organic instruments", "country",
            ],
        ),
    ]

    def __init__(self) -> None:
        self._by_slug = {g.slug: g for g in self.GENRES}

    def all_genres(self) -> List[GenreProfile]:
        return list(self.GENRES)

    def get_genre(self, slug: str) -> GenreProfile:
        if slug not in self._by_slug:
            raise KeyError(f"Unknown genre slug: {slug!r}. Available: {list(self._by_slug)}")
        return self._by_slug[slug]

    def curate_session(self) -> List[dict]:
        """
        セッション用プロンプトリストを生成して返す。

        各エントリに generation_seed を付与。
        make_instrumental=True、continue_clip_id=None を常に強制。
        商用NGキーワードが含まれた場合は自動サニタイズ + 警告ログ。
        """
        prompts = []
        for genre in self.GENRES:
            seed = generate_seed()
            style_prompt = genre.build_prompt(n_tags=4, seed=seed)
            prompts.append(
                {
                    "genre_name":        genre.name,
                    "genre_slug":        genre.slug,
                    "bpm":               genre.bpm,
                    # ── 安全ロック (絶対に変更禁止) ──────────────────────
                    "make_instrumental": True,       # ボーカル禁止
                    "continue_clip_id":  None,       # 他者楽曲への継続禁止
                    "is_remix":          False,       # リミックス禁止
                    "is_extend":         False,       # 拡張生成禁止
                    # ── プロンプト ────────────────────────────────────────
                    "style_prompt":      style_prompt,
                    "negative_prompt":   genre.build_negative(),
                    # ── 証拠台帳用シード ──────────────────────────────────
                    "generation_seed":   seed,
                }
            )
        return prompts

    def curate_single(self, slug: str) -> dict:
        """指定ジャンル 1 件のプロンプトを生成する。"""
        genre = self.get_genre(slug)
        seed = generate_seed()
        style_prompt = genre.build_prompt(n_tags=4, seed=seed)
        return {
            "genre_name":        genre.name,
            "genre_slug":        genre.slug,
            "bpm":               genre.bpm,
            "make_instrumental": True,
            "continue_clip_id":  None,
            "is_remix":          False,
            "is_extend":         False,
            "style_prompt":      style_prompt,
            "negative_prompt":   genre.build_negative(),
            "generation_seed":   seed,
        }

    def describe(self) -> None:
        """登録ジャンルの概要をプリントする (デバッグ用)。"""
        for g in self.GENRES:
            print(f"[{g.slug:12}] {g.name}  BPM={g.bpm}  tags={len(g.style_tags)}")
