"""
Trend Curator — All k Music
────────────────────────────────────────────────────────────────────────
4ジャンルの GenreProfile を管理し、Suno AI 向け高品質スタイルプロンプトを
セッションごとにランダムに組み合わせて生成する。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List


@dataclass
class GenreProfile:
    """1つのジャンルに対応するプロファイル。"""

    name: str
    slug: str              # ファイル名・ログの識別子
    bpm: int
    style_tags: List[str]  # Suno の "tags" フィールドに渡す候補群
    negative_tags: List[str] = field(default_factory=list)
    make_instrumental: bool = True

    def build_prompt(self, n_tags: int = 4) -> str:
        """
        style_tags からランダムに n_tags 個選んでカンマ区切りのプロンプトを生成。
        実行ごとに異なる組み合わせになることで楽曲の多様性が生まれる。
        """
        selected = random.sample(self.style_tags, min(n_tags, len(self.style_tags)))
        return ", ".join(selected)

    def build_negative(self) -> str:
        return ", ".join(self.negative_tags)


class TrendCurator:
    """
    4つのコアジャンルを管理し、セッション用プロンプトを生成するエージェント。

    各ジャンルのスタイルタグは Suno AI が最高品質のインストゥルメンタルを
    出力できるように設計されている。
    """

    # ── ジャンルマスター定義 ──────────────────────────────────────────────
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
        GenreProfile(
            name="EDM Glitch Hop",
            slug="edm",
            bpm=140,
            style_tags=[
                "TheFatRat style uplifting EDM",
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
                "cinematic intro",
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
        GenreProfile(
            name="Synthwave Retro",
            slug="synthwave",
            bpm=118,
            style_tags=[
                "80s synthwave retro futurism",
                "outrun driving night highway",
                "neon city aesthetic",
                "Blade Runner inspired soundtrack",
                "analog polysynth chords",
                "gated reverb drum machine",
                "catchy retrowave melody",
                "dark cinematic synthwave",
                "electric guitar solo 80s",
                "vaporwave nostalgia",
                "pulsing bassline arpeggio",
                "chromatic FM synth leads",
                "classic Roland Jupiter sound",
                "Miami Vice sunset vibes",
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

    # ── Public API ────────────────────────────────────────────────────────

    def all_genres(self) -> List[GenreProfile]:
        return list(self.GENRES)

    def get_genre(self, slug: str) -> GenreProfile:
        if slug not in self._by_slug:
            raise KeyError(f"Unknown genre slug: {slug!r}. Available: {list(self._by_slug)}")
        return self._by_slug[slug]

    def curate_session(self) -> List[dict]:
        """
        セッション用のプロンプトリストを生成して返す。
        タグ選択はランダムなので毎回異なる楽曲バリエーションが生まれる。
        """
        prompts = []
        for genre in self.GENRES:
            prompts.append({
                "genre_name":       genre.name,
                "genre_slug":       genre.slug,
                "bpm":              genre.bpm,
                "make_instrumental": genre.make_instrumental,
                "style_prompt":     genre.build_prompt(),
                "negative_prompt":  genre.build_negative(),
            })
        return prompts

    def describe(self) -> None:
        """登録ジャンルの概要をプリントする（デバッグ用）。"""
        for g in self.GENRES:
            print(f"[{g.slug:12}] {g.name}  BPM={g.bpm}  tags={len(g.style_tags)}")
