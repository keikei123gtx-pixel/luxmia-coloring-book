#!/usr/bin/env python3
"""
Auto Coloring Book Generator for Amazon KDP — Multi-Agent Architecture
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent 1 │ Orchestrator Agent      │ Gemini: generates coloring themes
Agent 2 │ Prompt Engineer Agent   │ Gemini: expands each theme into a
        │                         │   precise Pollinations AI image prompt
Agent 3 │ KDP Marketing Agent     │ Gemini: generates SEO metadata for KDP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Image generation : Pollinations AI / Flux  (free, no API key required)
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
from google import genai

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
A4_WIDTH_PX = int(A4_WIDTH_MM / 25.4 * DPI)   # 2480 px
A4_HEIGHT_PX = int(A4_HEIGHT_MM / 25.4 * DPI)  # 3508 px

BINARIZE_THRESHOLD = 200
NUM_THEMES = 5
MAX_RETRIES = 3
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BASE_DELAY = 15.0   # Gemini free tier: 10 RPM → 15s margin
IMAGE_BASE_DELAY = 8.0
IMAGE_COOLDOWN = 5.0
POLLINATIONS_URL = "https://image.pollinations.ai/prompt"

# Mandatory style tags injected into every image prompt (Prompt Engineer Agent)
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


# ---------------------------------------------------------------------------
# Utility: exponential-backoff retry
# ---------------------------------------------------------------------------
def retry(func, *args, retries: int = MAX_RETRIES, base_delay: float = 10.0, **kwargs):
    """
    Call func(*args, **kwargs) with exponential backoff.
    `retries` and `base_delay` are consumed here, NOT forwarded to func.
    """
    last_exc: Exception = RuntimeError("retry() invoked with retries=0")
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
                logger.error("All %d attempts failed: %s", retries, exc)
    raise last_exc


# ===========================================================================
# Agent 1: Orchestrator Agent
# Role: Decide the 5 coloring book themes for this book.
# ===========================================================================
def orchestrator_agent(client: genai.Client) -> list[str]:
    """Generate 5 coloring book themes via Gemini."""
    prompt = (
        "You are an expert coloring book designer for children aged 4-8.\n"
        "Generate exactly 5 unique, simple, and imaginative coloring book page themes in English.\n"
        "Good focus areas: friendly animals, nature scenery, simple flowers and plants, "
        "fantasy creatures, or cheerful everyday objects.\n\n"
        "Rules:\n"
        "- Return ONLY a numbered list (1. through 5.), one theme per line.\n"
        "- Keep each theme short and clear — a child should instantly picture it.\n"
        "- No extra commentary, preamble, or blank lines between items.\n\n"
        "Generate now:"
    )

    logger.info("[Agent 1 / Orchestrator] Generating themes with %s …", GEMINI_MODEL)
    response = retry(
        client.models.generate_content,
        retries=MAX_RETRIES,
        base_delay=GEMINI_BASE_DELAY,
        model=GEMINI_MODEL,
        contents=prompt,
    )

    themes: list[str] = []
    for line in response.text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0].isdigit() or line.startswith("-"):
            theme = line.split(".", 1)[-1].split(")", 1)[-1].strip(" -")
            if theme:
                themes.append(theme)

    if not themes:
        raise ValueError(f"Could not parse themes from Gemini response:\n{response.text}")

    themes = themes[:NUM_THEMES]
    logger.info("[Agent 1 / Orchestrator] %d themes ready:", len(themes))
    for i, t in enumerate(themes, 1):
        logger.info("  %d. %s", i, t)
    return themes


# ===========================================================================
# Agent 2: Prompt Engineer Agent
# Role: Expand a raw theme into a precision image prompt for Pollinations AI.
# ===========================================================================

# Fallback used if Gemini call fails
_PROMPT_FALLBACK = (
    "{theme}, simple children coloring page, {pos}, {neg}"
)

def prompt_engineer_agent(client: genai.Client, theme: str) -> str:
    """
    Expand `theme` into an optimised Pollinations AI (Flux) prompt.
    Guarantees LINEART_POSITIVE and LINEART_NEGATIVE are always present.
    Falls back to a safe default on API error.
    """
    instruction = f"""You are an expert AI image-prompt engineer specialising in children's \
coloring book line art.

Task: Transform the theme below into a high-quality Pollinations AI (Flux model) image prompt.

Theme: "{theme}"

Hard requirements:
1. Describe the subject clearly and simply — a 5-year-old should love to color it.
2. The prompt MUST contain these exact style tags verbatim:
   "{LINEART_POSITIVE}"
3. The prompt MUST end with these negative constraints verbatim:
   "{LINEART_NEGATIVE}"
4. Total prompt length: under 200 words.
5. Output ONLY the final prompt text. No labels, no quotes, no explanation."""

    logger.info("  [Agent 2 / Prompt Engineer] Expanding: "%s"", theme[:55])
    try:
        response = retry(
            client.models.generate_content,
            retries=MAX_RETRIES,
            base_delay=GEMINI_BASE_DELAY,
            model=GEMINI_MODEL,
            contents=instruction,
        )
        expanded = response.text.strip()

        # Safety net: inject mandatory tags if Gemini omitted them
        if LINEART_POSITIVE not in expanded:
            expanded = f"{expanded}, {LINEART_POSITIVE}"
        if LINEART_NEGATIVE not in expanded:
            expanded = f"{expanded}, {LINEART_NEGATIVE}"

        logger.info("  [Agent 2 / Prompt Engineer] Done (%d chars)", len(expanded))
        return expanded

    except Exception as exc:
        logger.warning(
            "  [Agent 2 / Prompt Engineer] FAILED (%s) — using fallback prompt", exc
        )
        return _PROMPT_FALLBACK.format(
            theme=theme, pos=LINEART_POSITIVE, neg=LINEART_NEGATIVE
        )


# ===========================================================================
# Agent 3: KDP Marketing Agent
# Role: Generate SEO-optimised Amazon KDP metadata and save it to a text file.
# ===========================================================================

_KDP_META_FALLBACK = """\
■ Main Title: Fun Coloring Pages for Kids
■ Subtitle: Coloring Book for Kids Ages 4-8, Featuring 5 Simple Clean Line Art Pages
■ 7 Keywords: kids coloring book ages 4-8, simple coloring pages for toddlers, easy line art coloring book, preschool activity book printable, children coloring pages animals, beginner coloring book for kids, fun coloring activity for kindergarten
■ Description:
<p>Give your child the gift of creativity with this charming coloring book! Every page is filled with bold, clean line art designed for little hands and growing imaginations.</p>
<ul>
<li>5 original, hand-crafted illustrations — no clip art</li>
<li>Extra-thick outlines make it easy for young children to stay inside the lines</li>
<li>Printed on bright white paper for vibrant crayon and marker results</li>
<li>Screen-free, quiet activity perfect for home or travel</li>
<li>A thoughtful gift for birthdays, holidays, or just because</li>
</ul>
<p>Order today and watch your child's confidence and creativity bloom, one page at a time!</p>"""

def kdp_marketing_agent(client: genai.Client, themes: list[str]) -> str:
    """
    Generate Amazon KDP SEO metadata based on the book's themes.
    Returns the formatted metadata string and saves it to output/kdp_meta.txt.
    Falls back to a safe default on API error.
    """
    theme_list = "\n".join(f"- {t}" for t in themes)
    instruction = f"""You are a seasoned Amazon KDP publishing consultant and SEO copywriter.

Create fully optimised metadata for a children's coloring book (ages 4-8) whose pages depict:
{theme_list}

Output EXACTLY in this format — keep every ■ symbol and label intact:

■ Main Title: [concise, catchy English title, max 60 characters]
■ Subtitle: [descriptive subtitle with age range and page count, KDP-compliant, max 150 characters]
■ 7 Keywords: [seven long-tail Amazon search phrases, comma-separated, low-to-medium competition]
■ Description:
[HTML-compatible product description, 150-300 words, with bullet points covering features and benefits]

Strict rules:
- Keywords must be phrases real shoppers type (e.g. "easy coloring pages for kids 4 6 8")
- Do NOT use competitor brand names, "best", "#1", or any medical/health claims
- Mention: age range, bold outlines, gift-worthiness, creativity/focus benefits
- Output ONLY the formatted block. No preamble, no explanation, nothing else."""

    logger.info("[Agent 3 / KDP Marketing] Generating KDP metadata …")
    try:
        response = retry(
            client.models.generate_content,
            retries=MAX_RETRIES,
            base_delay=GEMINI_BASE_DELAY,
            model=GEMINI_MODEL,
            contents=instruction,
        )
        meta = response.text.strip()
        logger.info("[Agent 3 / KDP Marketing] Done (%d chars)", len(meta))
        return meta

    except Exception as exc:
        logger.warning(
            "[Agent 3 / KDP Marketing] FAILED (%s) — using fallback metadata", exc
        )
        return _KDP_META_FALLBACK


# ---------------------------------------------------------------------------
# Image generation via Pollinations AI (Flux model)
# ---------------------------------------------------------------------------
def generate_image(image_prompt: str, output_path: Path) -> Optional[Path]:
    seed = random.randint(1, 999_999)
    encoded = urllib.parse.quote(image_prompt)
    url = (
        f"{POLLINATIONS_URL}/{encoded}"
        f"?width=1024&height=1024&model=flux&nologo=true&seed={seed}"
    )

    logger.info("  [Image Gen] Pollinations AI request (seed=%d) …", seed)

    def _fetch() -> bytes:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            raise ValueError(f"Unexpected Content-Type: {content_type!r}")
        return r.content

    try:
        image_data = retry(_fetch, retries=MAX_RETRIES, base_delay=IMAGE_BASE_DELAY)
        output_path.write_bytes(image_data)
        logger.info("  [Image Gen] Saved → %s", output_path.name)
        return output_path
    except Exception as exc:
        logger.error("  [Image Gen] FAILED: %s — skipping this page", exc)
        return None


# ---------------------------------------------------------------------------
# Image processing: 300 DPI + hard binarization
# ---------------------------------------------------------------------------
def process_image(src: Path, dst: Path) -> Optional[Path]:
    try:
        with Image.open(src) as img:
            if img.mode != "L":
                img = img.convert("L")

            # Hard binarization: eliminate all gray tones
            img = img.point(lambda p: 255 if p > BINARIZE_THRESHOLD else 0)

            # Fit within A4 canvas (preserves aspect ratio)
            img.thumbnail((A4_WIDTH_PX, A4_HEIGHT_PX), Image.LANCZOS)

            # Re-binarize: LANCZOS resampling reintroduces anti-aliasing gray
            img = img.point(lambda p: 255 if p > BINARIZE_THRESHOLD else 0)

            # Centre on a white A4 canvas
            canvas = Image.new("L", (A4_WIDTH_PX, A4_HEIGHT_PX), 255)
            canvas.paste(img, ((A4_WIDTH_PX - img.width) // 2,
                                (A4_HEIGHT_PX - img.height) // 2))

            canvas.save(dst, dpi=(DPI, DPI))

        logger.info(
            "  [Process] → %s  (%dx%d @ %d DPI)", dst.name, A4_WIDTH_PX, A4_HEIGHT_PX, DPI
        )
        return dst

    except Exception as exc:
        logger.error("  [Process] FAILED: %s — skipping this page", exc)
        return None


# ---------------------------------------------------------------------------
# PDF assembly
# ---------------------------------------------------------------------------
def create_pdf(image_paths: list[Path], output_path: Path) -> bool:
    if not image_paths:
        logger.error("[PDF] No processed images — cannot create PDF.")
        return False
    try:
        a4_pt = (img2pdf.mm_to_pt(A4_WIDTH_MM), img2pdf.mm_to_pt(A4_HEIGHT_MM))
        layout_fun = img2pdf.get_layout_fun(a4_pt)
        pdf_bytes = img2pdf.convert([str(p) for p in image_paths], layout_fun=layout_fun)
        output_path.write_bytes(pdf_bytes)
        size_mb = output_path.stat().st_size / 1_048_576
        logger.info(
            "[PDF] Saved → %s  (%.1f MB, %d pages)", output_path, size_mb, len(image_paths)
        )
        return True
    except Exception as exc:
        logger.error("[PDF] FAILED: %s", exc)
        return False


# ===========================================================================
# Main orchestration
# ===========================================================================
def main() -> None:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        logger.error("GEMINI_API_KEY is not set.")
        sys.exit(1)

    client = genai.Client(api_key=gemini_key)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # ── Agent 1: Orchestrator — decide themes ─────────────────────────────
    try:
        themes = orchestrator_agent(client)
    except Exception as exc:
        logger.error("Fatal — Orchestrator Agent failed: %s", exc)
        sys.exit(1)

    processed_pages: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="coloring_book_") as tmpdir:
        tmp = Path(tmpdir)

        for idx, theme in enumerate(themes, 1):
            logger.info(
                "\n══ Page %d/%d ══════════════════════════════════════════════",
                idx, len(themes),
            )
            logger.info("  Theme: %s", theme)

            # ── Agent 2: Prompt Engineer — craft the image prompt ──────────
            image_prompt = prompt_engineer_agent(client, theme)

            raw_path  = tmp / f"raw_{idx:02d}.png"
            page_path = tmp / f"page_{idx:02d}.png"

            # ── Image generation ───────────────────────────────────────────
            downloaded = generate_image(image_prompt, raw_path)
            if downloaded is None:
                continue

            # ── Image processing ───────────────────────────────────────────
            processed = process_image(raw_path, page_path)
            if processed is not None:
                processed_pages.append(page_path)

            if idx < len(themes):
                logger.info("  Waiting %.0fs …", IMAGE_COOLDOWN)
                time.sleep(IMAGE_COOLDOWN)

        logger.info("\n%d/%d pages ready.", len(processed_pages), len(themes))

        if not processed_pages:
            logger.error("No pages were generated — aborting.")
            sys.exit(1)

        # ── PDF assembly ───────────────────────────────────────────────────
        if not create_pdf(processed_pages, output_dir / "output.pdf"):
            sys.exit(1)

    # ── Agent 3: KDP Marketing — generate and save metadata ───────────────
    kdp_meta = kdp_marketing_agent(client, themes)
    meta_path = output_dir / "kdp_meta.txt"
    meta_path.write_text(kdp_meta, encoding="utf-8")
    logger.info("[Agent 3 / KDP Marketing] Saved → %s", meta_path)

    logger.info(
        "\nAll done!\n"
        "  • output/output.pdf   — print-ready coloring book\n"
        "  • output/kdp_meta.txt — KDP SEO metadata"
    )


if __name__ == "__main__":
    main()
