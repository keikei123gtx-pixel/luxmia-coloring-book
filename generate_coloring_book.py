#!/usr/bin/env python3
"""
LUXMIA Company — High-Level Multi-Agent Coloring Book System
═══════════════════════════════════════════════════════════════════════════════
Skill        │ Agent                        │ Role
─────────────┼──────────────────────────────┼──────────────────────────────────
find-skills  │ SkillRegistry (Hub)          │ 司令塔: routes every task
trend-plan   │ TrendPlanningAgent (CEO)     │ KDP需要分析・テーマ決定・戦略ログ
prompt-eng   │ PromptEngineerAgent          │ 画像プロンプト精密化
canvas-proc  │ CanvasImageProcessorAgent    │ 画像処理・品質メトリクス算出
ux-review    │ ColoringUXExpertAgent        │ 塗り絵品質・バケツ塗り適性レビュー
kdp-sns      │ KDPAndSNSMarketingAgent      │ KDP SEO + SNS集客コンテンツ生成
═══════════════════════════════════════════════════════════════════════════════
Image source : Pollinations AI / Flux  (completely free, no API key)
Knowledge    : logs/strategy_assets.md  (append-only, committed back to repo)
Outputs      : output/output.pdf  |  output/kdp_and_sns_meta.txt
"""

from __future__ import annotations

import os
import sys
import time
import random
import logging
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from PIL import Image, ImageStat
import img2pdf
from google import genai

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
DPI = 300
A4_W_MM, A4_H_MM = 210, 297
A4_W_PX = int(A4_W_MM / 25.4 * DPI)   # 2480
A4_H_PX = int(A4_H_MM / 25.4 * DPI)   # 3508

BINARIZE_THRESHOLD = 200
NUM_THEMES = 5
MAX_RETRIES = 3
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_DELAY = 15.0   # free-tier: ~10 RPM
IMG_DELAY = 8.0
IMG_COOLDOWN = 5.0
POLLINATIONS_URL = "https://image.pollinations.ai/prompt"

# Mandatory style tags for the Prompt Engineer Agent
LINEART_POSITIVE = (
    "pure black and white outline vector, thick black contours, "
    "completely white background, zero shadows, zero shading, zero grayscale, "
    "clean line art, Scandinavian minimalist coloring page style for kids, high contrast"
)
LINEART_NEGATIVE = (
    "no color, no gradients, no realistic textures, no shadows, no shading, "
    "no photorealism, no watercolor, no pencil sketch marks, no gray tones, "
    "no intricate micro-details, no blurred edges, no dark backgrounds"
)

# UX quality thresholds
UX_MIN_WHITE_RATIO = 0.55   # at least 55 % white (coloring space)
UX_MAX_BLACK_RATIO = 0.35   # at most 35 % black (lines)
UX_MIN_BLACK_RATIO = 0.03   # at least 3 % black (actual lines exist)
UX_PASS_SCORE = 70          # minimum score to "pass" review


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ImageMetrics:
    white_ratio: float = 0.0   # % purely white pixels
    black_ratio: float = 0.0   # % purely black pixels
    gray_ratio: float = 0.0    # % residual gray (should be 0 after binarization)
    width: int = 0
    height: int = 0

@dataclass
class UXReport:
    theme: str
    score: int = 100
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    metrics: ImageMetrics = field(default_factory=ImageMetrics)

    def summary(self) -> str:
        status = "✓ PASS" if self.passed else "✗ FAIL"
        issues = "; ".join(self.issues) if self.issues else "none"
        return (
            f"{status} | score={self.score} | "
            f"white={self.metrics.white_ratio:.1%} "
            f"black={self.metrics.black_ratio:.1%} "
            f"gray={self.metrics.gray_ratio:.1%} | "
            f"issues: {issues}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Utility: exponential-backoff retry
# ─────────────────────────────────────────────────────────────────────────────
def retry(
    func: Callable,
    *args,
    retries: int = MAX_RETRIES,
    base_delay: float = 10.0,
    **kwargs,
) -> Any:
    """
    Call func(*args, **kwargs) with exponential back-off.
    `retries` and `base_delay` are consumed here, never forwarded to func.
    """
    last_exc: Exception = RuntimeError("retry() called with retries=0")
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = base_delay * (2 ** attempt)
                logger.warning(
                    "Attempt %d/%d failed: %s  →  retry in %.0fs …",
                    attempt + 1, retries, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error("All %d attempts exhausted: %s", retries, exc)
    raise last_exc


# ═════════════════════════════════════════════════════════════════════════════
# SkillRegistry — find-skills Hub (司令塔エージェント)
# ═════════════════════════════════════════════════════════════════════════════
class SkillRegistry:
    """
    Centralised skill-discovery hub.
    All agents register themselves here; the orchestration layer calls
    `dispatch(skill_name, **kwargs)` without needing to know implementation
    details.  Claude (or future meta-agents) can call `list_skills()` to
    discover what capabilities are available and route autonomously.
    """

    def __init__(self) -> None:
        self._registry: dict[str, dict] = {}

    def register(self, name: str, func: Callable, description: str) -> None:
        self._registry[name] = {"func": func, "description": description}
        logger.info("[SkillHub] ✚ %-22s │ %s", name, description)

    def dispatch(self, skill: str, **kwargs) -> Any:
        if skill not in self._registry:
            available = ", ".join(self._registry)
            raise KeyError(f"Unknown skill '{skill}'. Available: {available}")
        logger.info("[SkillHub] ▶ → %s", skill)
        return self._registry[skill]["func"](**kwargs)

    def list_skills(self) -> dict[str, str]:
        return {k: v["description"] for k, v in self._registry.items()}


# ═════════════════════════════════════════════════════════════════════════════
# Agent ①: TrendPlanningAgent  (CEO直属 — トレンド企画エージェント)
# ═════════════════════════════════════════════════════════════════════════════
_TREND_FALLBACK_THEMES = [
    "A fluffy bunny holding a flower in a meadow",
    "A friendly elephant splashing in a pond",
    "A smiling sun behind simple clouds",
    "A little house surrounded by trees and birds",
    "A playful kitten chasing a butterfly",
]
_TREND_FALLBACK_RATIONALE = (
    "Fallback themes (API unavailable): classic safe-bet animals and nature "
    "scenes proven to perform well in KDP children's coloring books."
)

class TrendPlanningAgent:
    """
    Analyses KDP/SNS demand to pick today's niche, decides 5 themes,
    and appends a dated strategy entry to logs/strategy_assets.md.
    """

    def __init__(self, client: genai.Client, log_path: Path) -> None:
        self.client = client
        self.log_path = log_path

    def __call__(self) -> tuple[list[str], str]:
        prompt = (
            "You are LUXMIA's Chief Creative Officer with deep knowledge of "
            "Amazon KDP trends, Pinterest viral content, and children's product SEO.\n\n"
            "Task: Perform a rapid market analysis and select today's coloring book niche.\n\n"
            "Step 1 — Identify the single highest-demand, lower-competition niche right now "
            "from: (a) simple animals for toddlers, (b) botanical/floral for adults, "
            "(c) geometric/mandala patterns, (d) fantasy creatures for kids, "
            "(e) seasonal/holiday themes.\n\n"
            "Step 2 — Generate exactly 5 unique coloring page themes for that niche.\n\n"
            "Step 3 — Write 2-3 sentences explaining WHY this niche was chosen today "
            "(market logic, search trends, low competition angle).\n\n"
            "Output format (keep labels exactly):\n"
            "NICHE: [niche name]\n"
            "THEMES:\n"
            "1. [theme]\n"
            "2. [theme]\n"
            "3. [theme]\n"
            "4. [theme]\n"
            "5. [theme]\n"
            "RATIONALE: [2-3 sentence explanation]"
        )

        logger.info("[TrendPlanning] Analysing KDP trends with %s …", GEMINI_MODEL)
        try:
            response = retry(
                self.client.models.generate_content,
                retries=MAX_RETRIES,
                base_delay=GEMINI_DELAY,
                model=GEMINI_MODEL,
                contents=prompt,
            )
            raw = response.text.strip()
            themes, rationale = self._parse(raw)
        except Exception as exc:
            logger.warning("[TrendPlanning] API failed (%s) — using fallback themes.", exc)
            themes = _TREND_FALLBACK_THEMES
            rationale = _TREND_FALLBACK_RATIONALE

        self._append_log(themes, rationale)
        logger.info("[TrendPlanning] %d themes confirmed.", len(themes))
        for i, t in enumerate(themes, 1):
            logger.info("  %d. %s", i, t)
        return themes, rationale

    @staticmethod
    def _parse(text: str) -> tuple[list[str], str]:
        themes: list[str] = []
        rationale = ""
        in_themes = False
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("THEMES:"):
                in_themes = True
                continue
            if line.upper().startswith("RATIONALE:"):
                in_themes = False
                rationale = line.split(":", 1)[-1].strip()
                continue
            if in_themes and line and line[0].isdigit():
                theme = line.split(".", 1)[-1].strip()
                if theme:
                    themes.append(theme)
        if not themes:
            raise ValueError("Could not parse THEMES block from Gemini response.")
        return themes[:NUM_THEMES], rationale

    def _append_log(self, themes: list[str], rationale: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        theme_lines = "\n".join(f"  {i}. {t}" for i, t in enumerate(themes, 1))
        entry = (
            f"\n## Run: {now}\n\n"
            f"### Market Rationale\n{rationale}\n\n"
            f"### Selected Themes\n{theme_lines}\n\n"
            f"---\n"
        )
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
        logger.info("[TrendPlanning] Strategy log appended → %s", self.log_path)


# ═════════════════════════════════════════════════════════════════════════════
# Agent ②: PromptEngineerAgent  (デザイン部署)
# ═════════════════════════════════════════════════════════════════════════════
class PromptEngineerAgent:
    """
    Transforms a raw theme into a precision Pollinations AI image prompt.
    Guarantees LINEART_POSITIVE and LINEART_NEGATIVE are always present.
    """

    def __init__(self, client: genai.Client) -> None:
        self.client = client

    def __call__(self, theme: str) -> str:
        instruction = (
            "You are an elite AI image-prompt engineer specialising in children's "
            "coloring book line art for Pollinations AI (Flux model).\n\n"
            f"Theme: \"{theme}\"\n\n"
            "Task: Write a single optimised image prompt.\n\n"
            "Hard rules:\n"
            "1. Describe the subject concisely — a 5-year-old must love it.\n"
            f"2. Include these style tags verbatim:\n   {LINEART_POSITIVE}\n"
            f"3. End with these negative constraints verbatim:\n   {LINEART_NEGATIVE}\n"
            "4. Total length: under 180 words.\n"
            "5. Output ONLY the final prompt. No labels, no quotes, no explanation."
        )

        logger.info("  [PromptEng] Crafting prompt for: %s", theme[:55])
        try:
            response = retry(
                self.client.models.generate_content,
                retries=MAX_RETRIES,
                base_delay=GEMINI_DELAY,
                model=GEMINI_MODEL,
                contents=instruction,
            )
            prompt = response.text.strip()
            # Safety net: inject mandatory tags if Gemini omitted them
            if LINEART_POSITIVE not in prompt:
                prompt = f"{prompt}, {LINEART_POSITIVE}"
            if LINEART_NEGATIVE not in prompt:
                prompt = f"{prompt}, {LINEART_NEGATIVE}"
            logger.info("  [PromptEng] Done (%d chars)", len(prompt))
            return prompt
        except Exception as exc:
            logger.warning("  [PromptEng] API failed (%s) — using fallback prompt.", exc)
            return f"{theme}, {LINEART_POSITIVE}, {LINEART_NEGATIVE}"


# ═════════════════════════════════════════════════════════════════════════════
# Agent ③: CanvasImageProcessorAgent  (アルゴリズム特化)
# ═════════════════════════════════════════════════════════════════════════════
class CanvasImageProcessorAgent:
    """
    Processes a raw PNG into a print-ready A4/300-DPI binarised image.
    Returns (processed_path | None, ImageMetrics) for downstream UX review.

    Optimisations vs. naive approach:
    - Double binarisation pass (pre- and post-LANCZOS) to eliminate
      anti-aliasing gray that LANCZOS resampling re-introduces.
    - Memory-safe: image opened in context manager, temp canvas discarded.
    - DPI metadata embedded for both PDF and KDP upload compatibility.
    """

    def __call__(self, src: Path, dst: Path) -> tuple[Optional[Path], ImageMetrics]:
        metrics = ImageMetrics()
        try:
            with Image.open(src) as img:
                # ① Normalise to grayscale
                if img.mode != "L":
                    img = img.convert("L")

                # ② Hard binarisation — strip ALL gray tones
                img = img.point(lambda p: 255 if p > BINARIZE_THRESHOLD else 0)

                # ③ Fit within A4 canvas (aspect-ratio preserved)
                img.thumbnail((A4_W_PX, A4_H_PX), Image.LANCZOS)

                # ④ Re-binarise — LANCZOS reintroduces anti-aliasing gray
                img = img.point(lambda p: 255 if p > BINARIZE_THRESHOLD else 0)

                # ⑤ Compute quality metrics before canvas paste
                total = img.width * img.height
                hist = img.histogram()   # 256 bins for mode L
                white_px = hist[255]
                black_px = hist[0]
                gray_px = total - white_px - black_px
                metrics = ImageMetrics(
                    white_ratio=white_px / total,
                    black_ratio=black_px / total,
                    gray_ratio=gray_px / total,
                    width=img.width,
                    height=img.height,
                )

                # ⑥ Centre on white A4 canvas
                canvas = Image.new("L", (A4_W_PX, A4_H_PX), 255)
                canvas.paste(img, ((A4_W_PX - img.width) // 2,
                                   (A4_H_PX - img.height) // 2))

                # ⑦ Save with 300 DPI metadata
                canvas.save(dst, dpi=(DPI, DPI))

            logger.info(
                "  [CanvasProc] → %s  white=%.1f%% black=%.1f%% gray=%.1f%%",
                dst.name,
                metrics.white_ratio * 100,
                metrics.black_ratio * 100,
                metrics.gray_ratio * 100,
            )
            return dst, metrics

        except Exception as exc:
            logger.error("  [CanvasProc] FAILED: %s — page skipped.", exc)
            return None, metrics


# ═════════════════════════════════════════════════════════════════════════════
# Agent ④: ColoringUXExpertAgent  (品質管理・UXレビュー)
# ═════════════════════════════════════════════════════════════════════════════
class ColoringUXExpertAgent:
    """
    Evaluates each processed image from a coloring-book UX perspective:
    - Is the background clean? (residual gray → KDP audit risk)
    - Is there enough white space for a child to color freely?
    - Are the lines neither too sparse nor too dense?
    - Bucket-fill safety: an image dominated by enclosed regions scores higher.

    Pure Pillow-based — no extra API calls, no latency added.
    """

    def __call__(self, metrics: ImageMetrics, theme: str) -> UXReport:
        report = UXReport(theme=theme, metrics=metrics)

        # Rule 1 — Residual gray (KDP printing risk)
        if metrics.gray_ratio > 0.001:
            report.score -= 25
            report.issues.append(
                f"Gray pixels remain ({metrics.gray_ratio:.2%}) — binarization incomplete"
            )

        # Rule 2 — Insufficient white space (too dark for children)
        if metrics.white_ratio < UX_MIN_WHITE_RATIO:
            report.score -= 20
            report.issues.append(
                f"White space too low ({metrics.white_ratio:.1%} < {UX_MIN_WHITE_RATIO:.0%})"
            )

        # Rule 3 — Line density too high (claustrophobic, bucket-fill bleeds)
        if metrics.black_ratio > UX_MAX_BLACK_RATIO:
            report.score -= 15
            report.issues.append(
                f"Too many black pixels ({metrics.black_ratio:.1%} > {UX_MAX_BLACK_RATIO:.0%}) "
                "— bucket-fill bleed risk"
            )

        # Rule 4 — Almost no lines (barely any illustration)
        if metrics.black_ratio < UX_MIN_BLACK_RATIO:
            report.score -= 20
            report.issues.append(
                f"Too few lines ({metrics.black_ratio:.1%} < {UX_MIN_BLACK_RATIO:.0%})"
            )

        report.passed = report.score >= UX_PASS_SCORE
        logger.info("  [UX Expert] %s", report.summary())
        return report


# ═════════════════════════════════════════════════════════════════════════════
# Agent ⑤: KDPAndSNSMarketingAgent  (マーケティング・広報エージェント)
# ═════════════════════════════════════════════════════════════════════════════
_KDP_SNS_FALLBACK = """\
■ Main Title: Fun Coloring Pages for Kids
■ Subtitle: Coloring Book for Kids Ages 4-8 | 5 Bold Line Art Pages Perfect for Little Hands
■ 7 Keywords: kids coloring book ages 4-8, simple coloring pages for toddlers, easy line art book for children, preschool activity coloring pages, beginner coloring for kindergarten, fun animal coloring book kids, printable coloring pages children
■ Description:
<p>Spark your child's creativity with this charming coloring book! Every page features bold, clean line art designed for little hands and growing imaginations.</p>
<ul>
<li>5 original illustrations — no clip art, no reprints</li>
<li>Extra-thick outlines — easy to color inside the lines</li>
<li>Bright white paper optimised for crayons, markers, and colored pencils</li>
<li>Screen-free quiet activity, perfect for home or travel</li>
<li>Thoughtful gift for birthdays and holidays</li>
</ul>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 INSTAGRAM POST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎨 NEW DROP — Color your world! Our new kids' coloring book is here, packed with 5 adorable pages your little one will love. Perfect for quiet time, travel, or gift-giving. Grab yours today! 🖍️✨
#kidscoloringbook #coloringpages #kidsactivities #toddleractivities #printablecoloring #kidsart #coloringforkids #kdppublishing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎬 YOUTUBE SHORTS SCRIPT (9:16)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[HOOK — 0:00–0:03]
"Looking for the PERFECT gift for your little artist?" 🎨

[SHOWCASE — 0:03–0:12]
Show pages flipping, bold clean outlines visible. Voiceover: "5 original illustrations, thick outlines, totally screen-free!"

[CTA — 0:12–0:15]
"Link in bio — get it on Amazon KDP today!" 🛒
"""

class KDPAndSNSMarketingAgent:
    """
    Generates Amazon KDP SEO metadata AND SNS promotional content.
    Saves everything to output/kdp_and_sns_meta.txt.
    """

    def __init__(self, client: genai.Client) -> None:
        self.client = client

    def __call__(
        self,
        themes: list[str],
        ux_reports: list[UXReport],
        output_path: Path,
    ) -> str:
        theme_list = "\n".join(f"- {t}" for t in themes)
        ux_summary = "\n".join(
            f"- Page {i+1}: {r.summary()}" for i, r in enumerate(ux_reports)
        )

        instruction = (
            "You are LUXMIA's Head of Marketing — Amazon KDP publishing expert "
            "and social media strategist.\n\n"
            "A children's coloring book (ages 4-8) has just been generated with these pages:\n"
            f"{theme_list}\n\n"
            "UX quality review results:\n"
            f"{ux_summary}\n\n"
            "Generate the complete marketing asset package in this EXACT format "
            "(keep every ■, ━, 📱, 🎬 symbol):\n\n"
            "■ Main Title: [catchy English title, max 60 chars]\n"
            "■ Subtitle: [age + page count + key benefit, KDP-compliant, max 150 chars]\n"
            "■ 7 Keywords: [seven long-tail Amazon search phrases, comma-separated]\n"
            "■ Description:\n"
            "[HTML-compatible, 150-300 words, bullet points, emphasise creativity + gift angle]\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📱 INSTAGRAM POST\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "[Engaging 3-4 sentence post with emojis + 8-10 relevant hashtags]\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🎬 YOUTUBE SHORTS SCRIPT (9:16)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "[3-section script: HOOK (0-3s), SHOWCASE (3-12s), CTA (12-15s)]\n\n"
            "Rules:\n"
            "- No competitor names, no 'best'/'#1', no medical claims\n"
            "- Keywords must be long-tail phrases with actual search intent\n"
            "- SNS copy must be copy-paste ready with hashtags\n"
            "- Output ONLY the formatted block."
        )

        logger.info("[KDP+SNS] Generating marketing assets …")
        try:
            response = retry(
                self.client.models.generate_content,
                retries=MAX_RETRIES,
                base_delay=GEMINI_DELAY,
                model=GEMINI_MODEL,
                contents=instruction,
            )
            content = response.text.strip()
            logger.info("[KDP+SNS] Done (%d chars)", len(content))
        except Exception as exc:
            logger.warning("[KDP+SNS] API failed (%s) — using fallback content.", exc)
            content = _KDP_SNS_FALLBACK

        header = (
            "═══════════════════════════════════════════════════════════════\n"
            f"  LUXMIA — KDP & SNS MARKETING ASSETS\n"
            f"  Generated: {date.today().isoformat()}\n"
            "═══════════════════════════════════════════════════════════════\n\n"
        )
        full = header + content
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(full, encoding="utf-8")
        logger.info("[KDP+SNS] Saved → %s", output_path)
        return full


# ─────────────────────────────────────────────────────────────────────────────
# Image generation — Pollinations AI / Flux
# ─────────────────────────────────────────────────────────────────────────────
def generate_image(image_prompt: str, output_path: Path) -> Optional[Path]:
    seed = random.randint(1, 999_999)
    encoded = urllib.parse.quote(image_prompt)
    url = (
        f"{POLLINATIONS_URL}/{encoded}"
        f"?width=1024&height=1024&model=flux&nologo=true&seed={seed}"
    )
    logger.info("  [ImageGen] Pollinations AI (seed=%d) …", seed)

    def _fetch() -> bytes:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "")
        if not ct.startswith("image/"):
            raise ValueError(f"Bad Content-Type: {ct!r}")
        return r.content

    try:
        data = retry(_fetch, retries=MAX_RETRIES, base_delay=IMG_DELAY)
        output_path.write_bytes(data)
        logger.info("  [ImageGen] Saved → %s", output_path.name)
        return output_path
    except Exception as exc:
        logger.error("  [ImageGen] FAILED: %s — skipping page.", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PDF assembly
# ─────────────────────────────────────────────────────────────────────────────
def create_pdf(image_paths: list[Path], output_path: Path) -> bool:
    if not image_paths:
        logger.error("[PDF] No images available — aborting.")
        return False
    try:
        a4_pt = (img2pdf.mm_to_pt(A4_W_MM), img2pdf.mm_to_pt(A4_H_MM))
        layout = img2pdf.get_layout_fun(a4_pt)
        pdf_bytes = img2pdf.convert([str(p) for p in image_paths], layout_fun=layout)
        output_path.write_bytes(pdf_bytes)
        mb = output_path.stat().st_size / 1_048_576
        logger.info("[PDF] Saved → %s (%.1f MB, %d pages)", output_path, mb, len(image_paths))
        return True
    except Exception as exc:
        logger.error("[PDF] FAILED: %s", exc)
        return False


# ═════════════════════════════════════════════════════════════════════════════
# Main orchestration
# ═════════════════════════════════════════════════════════════════════════════
def main() -> None:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        logger.error("GEMINI_API_KEY is not set.")
        sys.exit(1)

    client = genai.Client(api_key=gemini_key)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    log_path = Path("logs") / "strategy_assets.md"

    # ── Instantiate agents ────────────────────────────────────────────────
    trend_agent   = TrendPlanningAgent(client, log_path)
    prompt_agent  = PromptEngineerAgent(client)
    canvas_agent  = CanvasImageProcessorAgent()
    ux_agent      = ColoringUXExpertAgent()
    marketing_agent = KDPAndSNSMarketingAgent(client)

    # ── Build the SkillRegistry (find-skills hub) ─────────────────────────
    hub = SkillRegistry()
    hub.register("trend-planning",  trend_agent,      "KDP trend analysis + theme generation + strategy log")
    hub.register("prompt-engineer", prompt_agent,     "Expand theme → optimised Pollinations AI image prompt")
    hub.register("canvas-processor", canvas_agent,   "Binarise, resize, A4/300DPI + compute quality metrics")
    hub.register("coloring-ux-expert", ux_agent,     "Review image quality for coloring-book UX standards")
    hub.register("kdp-sns-marketing", marketing_agent, "Generate KDP SEO metadata + Instagram/YT-Shorts copy")

    logger.info("\n[SkillHub] Registered skills: %s\n", list(hub.list_skills()))

    # ── Agent ①: Trend Planning ───────────────────────────────────────────
    themes, _rationale = hub.dispatch("trend-planning")

    processed_pages: list[Path] = []
    ux_reports: list[UXReport] = []

    with tempfile.TemporaryDirectory(prefix="luxmia_") as tmpdir:
        tmp = Path(tmpdir)

        for idx, theme in enumerate(themes, 1):
            logger.info(
                "\n══ Page %d/%d ════════════════════════════════════════════════",
                idx, len(themes),
            )
            logger.info("  Theme: %s", theme)

            # ── Agent ②: Prompt Engineer ──────────────────────────────────
            image_prompt = hub.dispatch("prompt-engineer", theme=theme)

            raw_path  = tmp / f"raw_{idx:02d}.png"
            page_path = tmp / f"page_{idx:02d}.png"

            # ── Image generation ───────────────────────────────────────────
            downloaded = generate_image(image_prompt, raw_path)
            if downloaded is None:
                ux_reports.append(UXReport(theme=theme, score=0, passed=False,
                                           issues=["Image generation failed"]))
                continue

            # ── Agent ③: Canvas Image Processor ───────────────────────────
            processed, metrics = hub.dispatch(
                "canvas-processor", src=raw_path, dst=page_path
            )
            if processed is None:
                ux_reports.append(UXReport(theme=theme, score=0, passed=False,
                                           issues=["Image processing failed"],
                                           metrics=metrics))
                continue

            # ── Agent ④: UX Expert review ─────────────────────────────────
            report = hub.dispatch("coloring-ux-expert", metrics=metrics, theme=theme)
            ux_reports.append(report)

            processed_pages.append(page_path)

            if idx < len(themes):
                logger.info("  Waiting %.0fs (rate-limit cooldown) …", IMG_COOLDOWN)
                time.sleep(IMG_COOLDOWN)

    logger.info("\n%d/%d pages ready for PDF.", len(processed_pages), len(themes))
    if not processed_pages:
        logger.error("No pages generated — aborting.")
        sys.exit(1)

    # ── PDF assembly ──────────────────────────────────────────────────────
    if not create_pdf(processed_pages, output_dir / "output.pdf"):
        sys.exit(1)

    # ── Agent ⑤: KDP + SNS Marketing ─────────────────────────────────────
    hub.dispatch(
        "kdp-sns-marketing",
        themes=themes,
        ux_reports=ux_reports,
        output_path=output_dir / "kdp_and_sns_meta.txt",
    )

    passed = sum(1 for r in ux_reports if r.passed)
    logger.info(
        "\n✅ All done!\n"
        "  • output/output.pdf          — %d-page print-ready coloring book\n"
        "  • output/kdp_and_sns_meta.txt — KDP SEO + SNS copy\n"
        "  • logs/strategy_assets.md    — strategy knowledge base updated\n"
        "  • UX review: %d/%d pages passed",
        len(processed_pages), passed, len(ux_reports),
    )


if __name__ == "__main__":
    main()
