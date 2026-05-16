#!/usr/bin/env python3
"""
Auto Coloring Book Generator for Amazon KDP
Generates AI-powered coloring book pages and compiles them into an A4 PDF.
Image generation: Pollinations AI (https://image.pollinations.ai/) — completely free, no API key required.
"""

import os
import sys
import time
import random
import logging
import tempfile
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
from PIL import Image
import img2pdf
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DPI = 300
A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
# A4 canvas size at 300 DPI
A4_WIDTH_PX = int(A4_WIDTH_MM / 25.4 * DPI)   # 2480 px
A4_HEIGHT_PX = int(A4_HEIGHT_MM / 25.4 * DPI)  # 3508 px

BINARIZE_THRESHOLD = 200   # pixels above → white, below → black
NUM_THEMES = 5
MAX_RETRIES = 3
GEMINI_BASE_DELAY = 15.0   # seconds; Gemini free tier: 15 RPM
IMAGE_BASE_DELAY = 8.0     # seconds; Pollinations AI retry base delay
IMAGE_COOLDOWN = 5.0       # wait between successive Pollinations requests
POLLINATIONS_URL = "https://image.pollinations.ai/prompt"


# ---------------------------------------------------------------------------
# Utility: exponential-backoff retry
# ---------------------------------------------------------------------------
def retry(func, *args, retries: int = MAX_RETRIES, base_delay: float = 10.0, **kwargs):
    """
    Call func(*args, **kwargs) up to `retries` times with exponential backoff.
    `retries` and `base_delay` are consumed here and NOT forwarded to func.
    """
    last_exc: Exception = RuntimeError("retry called with retries=0")
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = base_delay * (2 ** attempt)
                logger.warning(
                    "Attempt %d/%d failed: %s  →  retrying in %.0fs …",
                    attempt + 1, retries, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error("All %d attempts failed: %s", retries, exc)
    raise last_exc


# ---------------------------------------------------------------------------
# Step 1: Theme generation via Gemini
# ---------------------------------------------------------------------------
def generate_themes(api_key: str) -> list[str]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = (
        "You are helping create an adult coloring book for women in their 40s-50s.\n"
        "Generate exactly 5 unique, calming, and therapeutically appealing coloring "
        "book page themes in English.\n"
        "Focus areas: intricate mandalas, botanical/floral illustrations, nature scenes, "
        "geometric patterns, or peaceful landscapes.\n\n"
        "Rules:\n"
        "- Return ONLY a numbered list (1. … 5.), one theme per line.\n"
        "- Each theme must be descriptive enough to generate a detailed illustration.\n"
        "- No extra commentary, preamble, or blank lines between items.\n\n"
        "Generate now:"
    )

    logger.info("Calling Gemini API (gemini-1.5-flash) to generate themes …")
    response = retry(
        model.generate_content,
        prompt,
        retries=MAX_RETRIES,
        base_delay=GEMINI_BASE_DELAY,
    )

    themes: list[str] = []
    for line in response.text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Accept lines that start with a digit (numbered list) or dash
        if line[0].isdigit() or line.startswith("-"):
            theme = line.split(".", 1)[-1].split(")", 1)[-1].strip(" -")
            if theme:
                themes.append(theme)

    if not themes:
        raise ValueError(
            f"Could not parse any themes from Gemini response:\n{response.text}"
        )

    if len(themes) < NUM_THEMES:
        logger.warning("Only %d themes parsed (expected %d).", len(themes), NUM_THEMES)

    themes = themes[:NUM_THEMES]
    logger.info("Themes generated:")
    for i, t in enumerate(themes, 1):
        logger.info("  %d. %s", i, t)
    return themes


# ---------------------------------------------------------------------------
# Step 2: Image generation via Pollinations AI (free, no API key required)
# https://image.pollinations.ai/prompt/{prompt}?model=flux&...
# ---------------------------------------------------------------------------
def generate_image(theme: str, output_path: Path) -> Optional[Path]:
    image_prompt = (
        f"{theme}, "
        "black and white line art, no shading, clean white background, "
        "bold thick outlines, intricate details suitable for adult coloring book, "
        "pure black lines on pure white background, no gray tones, no color fills, "
        "coloring book page style"
    )

    seed = random.randint(1, 999_999)
    encoded = urllib.parse.quote(image_prompt)
    url = (
        f"{POLLINATIONS_URL}/{encoded}"
        f"?width=1024&height=1024&model=flux&nologo=true&seed={seed}"
    )

    logger.info("  Requesting Pollinations AI (Flux model, seed=%d) …", seed)

    def _fetch() -> bytes:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            raise ValueError(f"Unexpected Content-Type from Pollinations: {content_type!r}")
        return r.content

    try:
        image_data = retry(_fetch, retries=MAX_RETRIES, base_delay=IMAGE_BASE_DELAY)
        output_path.write_bytes(image_data)
        logger.info("  Saved raw image → %s", output_path.name)
        return output_path

    except Exception as exc:
        logger.error("  Image generation FAILED: %s — this page will be skipped.", exc)
        return None


# ---------------------------------------------------------------------------
# Step 3: Image processing (300 DPI + binarization)
# ---------------------------------------------------------------------------
def process_image(src: Path, dst: Path) -> Optional[Path]:
    try:
        with Image.open(src) as img:
            # Ensure grayscale
            if img.mode != "L":
                img = img.convert("L")

            # Hard binarization: remove all gray tones
            img = img.point(lambda p: 255 if p > BINARIZE_THRESHOLD else 0)

            # Resize to fit within A4 canvas, preserving aspect ratio
            img.thumbnail((A4_WIDTH_PX, A4_HEIGHT_PX), Image.LANCZOS)

            # Re-binarize after LANCZOS resampling (which reintroduces gray)
            img = img.point(lambda p: 255 if p > BINARIZE_THRESHOLD else 0)

            # Center on white A4 canvas
            canvas = Image.new("L", (A4_WIDTH_PX, A4_HEIGHT_PX), 255)
            x_off = (A4_WIDTH_PX - img.width) // 2
            y_off = (A4_HEIGHT_PX - img.height) // 2
            canvas.paste(img, (x_off, y_off))

            # Save with embedded 300 DPI metadata
            canvas.save(dst, dpi=(DPI, DPI))

        logger.info("  Processed → %s  (%dx%d @ %d DPI)", dst.name, A4_WIDTH_PX, A4_HEIGHT_PX, DPI)
        return dst

    except Exception as exc:
        logger.error("  Image processing FAILED: %s — this page will be skipped.", exc)
        return None


# ---------------------------------------------------------------------------
# Step 4: PDF assembly
# ---------------------------------------------------------------------------
def create_pdf(image_paths: list[Path], output_path: Path) -> bool:
    if not image_paths:
        logger.error("No processed images available — cannot create PDF.")
        return False

    try:
        a4_pt = (img2pdf.mm_to_pt(A4_WIDTH_MM), img2pdf.mm_to_pt(A4_HEIGHT_MM))
        layout_fun = img2pdf.get_layout_fun(a4_pt)

        pdf_bytes = img2pdf.convert(
            [str(p) for p in image_paths],
            layout_fun=layout_fun,
        )
        output_path.write_bytes(pdf_bytes)
        size_mb = output_path.stat().st_size / 1_048_576
        logger.info("PDF saved → %s  (%.1f MB, %d pages)", output_path, size_mb, len(image_paths))
        return True

    except Exception as exc:
        logger.error("PDF creation FAILED: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not gemini_key:
        logger.error("Environment variable GEMINI_API_KEY is not set.")
        sys.exit(1)

    # Pollinations AI requires no API key — confirm here for clarity
    logger.info("Image generator: Pollinations AI (no API key required)")

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="coloring_book_") as tmpdir:
        tmp = Path(tmpdir)

        # ── Step 1: themes ────────────────────────────────────────────────
        try:
            themes = generate_themes(gemini_key)
        except Exception as exc:
            logger.error("Fatal: theme generation failed: %s", exc)
            sys.exit(1)

        # ── Steps 2-3: images ─────────────────────────────────────────────
        processed_pages: list[Path] = []

        for idx, theme in enumerate(themes, 1):
            logger.info("\n── Page %d/%d ─────────────────────────────────────", idx, len(themes))
            logger.info("  Theme: %s", theme)

            raw_path = tmp / f"raw_{idx:02d}.png"
            page_path = tmp / f"page_{idx:02d}.png"

            downloaded = generate_image(theme, raw_path)
            if downloaded is None:
                continue

            processed = process_image(raw_path, page_path)
            if processed is not None:
                processed_pages.append(page_path)

            # Small cooldown to be respectful of Pollinations' free service
            if idx < len(themes):
                logger.info("  Waiting %.0fs before next image call …", IMAGE_COOLDOWN)
                time.sleep(IMAGE_COOLDOWN)

        logger.info(
            "\n%d/%d pages successfully generated.", len(processed_pages), len(themes)
        )

        if not processed_pages:
            logger.error("No pages were generated — aborting.")
            sys.exit(1)

        # ── Step 4: PDF ───────────────────────────────────────────────────
        ok = create_pdf(processed_pages, output_dir / "output.pdf")
        if not ok:
            sys.exit(1)

    logger.info("\nAll done! output/output.pdf is ready for KDP upload.")


if __name__ == "__main__":
    main()
