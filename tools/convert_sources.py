#!/usr/bin/env python3
"""
convert_sources.py — Agent 5: source body converter

Converts cached HTML or PDF source bodies into reviewable plain text / Markdown
for resource authors to read and summarize. The output is UNTRUSTED EVIDENCE —
it must never be automatically promoted to an approved resource file.

Usage:
    python tools/convert_sources.py --input .cache/sources/<hash> --format html
    python tools/convert_sources.py --input .cache/sources/<hash> --format pdf
    python tools/convert_sources.py --sidecar resources/students/academic-model.source.json
    python tools/convert_sources.py --all --out .cache/converted

Output files are written to .cache/converted/ (gitignored).
Each output file is prefixed with a prominent UNTRUSTED EVIDENCE header.

Optional dependencies:
    HTML conversion: pip install beautifulsoup4 lxml
    PDF  conversion: pip install pdfminer.six   (or install poppler + pdftotext)
    If a dependency is missing, the tool reports it clearly and exits non-zero.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("convert_sources")

CACHE_DIR = Path(".cache/sources")
CONVERTED_DIR = Path(".cache/converted")

UNTRUSTED_HEADER = """\
<!-- ============================================================
  UNTRUSTED EVIDENCE — DO NOT COPY INTO RESOURCE FILES
  This file was automatically converted from a public source.
  It has not been reviewed, verified, or approved as resource content.
  Resource authors must write original summaries citing this material.
  Treat all text below as a raw source document, not as policy.
============================================================ -->

"""


# ---------------------------------------------------------------------------
# HTML conversion
# ---------------------------------------------------------------------------

def convert_html(body: bytes, source_url: str = "") -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise SystemExit(
            "HTML conversion requires beautifulsoup4:\n"
            "  pip install beautifulsoup4 lxml\n"
            "Install all dev dependencies with: pip install -e '.[dev]'"
        )

    soup = BeautifulSoup(body, "lxml")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "header", "footer",
                      "aside", "form", "noscript", "iframe", "svg", "button"]):
        tag.decompose()

    # Also remove common boilerplate by class/id heuristics
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        id_ = tag.get("id", "")
        if any(kw in classes.lower() or kw in id_.lower()
               for kw in ["nav", "menu", "sidebar", "footer", "header",
                           "breadcrumb", "skip", "cookie", "banner", "search-bar"]):
            tag.decompose()

    lines = []
    if source_url:
        lines.append(f"> Source URL: {source_url}\n")

    def process(tag) -> None:
        name = getattr(tag, "name", None)
        if name is None:
            text = str(tag).strip()
            if text:
                lines.append(text)
            return

        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(name[1])
            text = tag.get_text(" ", strip=True)
            if text:
                lines.append(f"\n{'#' * level} {text}\n")
        elif name == "p":
            text = tag.get_text(" ", strip=True)
            if text:
                lines.append(f"\n{text}\n")
        elif name in ("ul", "ol"):
            for li in tag.find_all("li", recursive=False):
                text = li.get_text(" ", strip=True)
                if text:
                    lines.append(f"- {text}")
            lines.append("")
        elif name == "table":
            rows = tag.find_all("tr")
            for i, row in enumerate(rows):
                cells = [td.get_text(" ", strip=True) for td in row.find_all(["th", "td"])]
                lines.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
            lines.append("")
        elif name == "a":
            text = tag.get_text(" ", strip=True)
            href = tag.get("href", "")
            if text and href:
                lines.append(f"[{text}]({href})")
            elif text:
                lines.append(text)
        elif name in ("div", "section", "article", "main"):
            for child in tag.children:
                process(child)
        else:
            text = tag.get_text(" ", strip=True)
            if text:
                lines.append(text)

    body_tag = soup.find("main") or soup.find("article") or soup.find("body") or soup
    for child in body_tag.children:
        process(child)

    # Collapse excessive blank lines
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return UNTRUSTED_HEADER + text.strip() + "\n"


# ---------------------------------------------------------------------------
# PDF conversion
# ---------------------------------------------------------------------------

def convert_pdf(body: bytes, source_url: str = "") -> str:
    # Try pdfminer.six first
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        import io
        text = pdfminer_extract(io.BytesIO(body))
    except ImportError:
        # Try subprocess pdftotext (poppler)
        try:
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(body)
                tmp_path = tmp.name
            result = subprocess.run(
                ["pdftotext", "-layout", tmp_path, "-"],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0:
                raise SystemExit(
                    "pdftotext failed. Install poppler-utils or pdfminer.six:\n"
                    "  pip install pdfminer.six\n"
                    "  # or: apt install poppler-utils / brew install poppler"
                )
            text = result.stdout.decode("utf-8", errors="replace")
            Path(tmp_path).unlink(missing_ok=True)
        except FileNotFoundError:
            raise SystemExit(
                "PDF conversion requires pdfminer.six or poppler pdftotext.\n"
                "Install one:\n"
                "  pip install pdfminer.six\n"
                "  # or: apt install poppler-utils / brew install poppler\n"
                "This is an optional dependency — HTML sources do not require it."
            )

    header = UNTRUSTED_HEADER
    if source_url:
        header += f"> Source URL: {source_url}\n\n"

    # Insert page markers
    pages = text.split("\f")
    marked = []
    for i, page in enumerate(pages, start=1):
        page = page.strip()
        if page:
            marked.append(f"\n---\n<!-- Page {i} -->\n\n{page}")
    return header + "\n".join(marked) + "\n"


# ---------------------------------------------------------------------------
# Cache lookup
# ---------------------------------------------------------------------------

def cache_entry_for_url(url: str) -> tuple[Optional[Path], Optional[dict]]:
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    cache_base = CACHE_DIR / url_hash[:2] / url_hash
    body_path = cache_base.with_suffix(".body")
    meta_path = cache_base.with_suffix(".meta.json")
    if not body_path.exists():
        return None, None
    meta = {}
    if meta_path.exists():
        try:
            with meta_path.open(encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass
    return body_path, meta


def convert_cached(
    body_path: Path,
    meta: dict,
    out_dir: Path,
    fmt: Optional[str] = None,
) -> Optional[Path]:
    body = body_path.read_bytes()
    source_url = meta.get("canonical_url", meta.get("url", ""))
    ct = meta.get("content_type", "")

    # Determine format
    if fmt is None:
        if "pdf" in ct:
            fmt = "pdf"
        else:
            fmt = "html"

    if fmt == "html":
        converted = convert_html(body, source_url)
        suffix = ".md"
    elif fmt == "pdf":
        converted = convert_pdf(body, source_url)
        suffix = ".txt"
    else:
        log.error("Unknown format: %s", fmt)
        return None

    sha = meta.get("sha256", hashlib.sha256(body).hexdigest())
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (sha[:16] + suffix)
    out_path.write_text(converted, encoding="utf-8")
    log.info("Converted → %s (%d chars)", out_path, len(converted))
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert cached source bodies to reviewable text. Output is UNTRUSTED EVIDENCE."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--input",
        type=Path,
        help="Path to a cache directory (e.g. .cache/sources/<hash>) or a .body file",
    )
    group.add_argument(
        "--sidecar",
        type=Path,
        help="Convert all cached sources referenced by a .source.json sidecar",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Convert all cached sources in .cache/sources/",
    )
    parser.add_argument(
        "--format",
        choices=["html", "pdf"],
        default=None,
        help="Force conversion format (default: inferred from content-type)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=CONVERTED_DIR,
        help="Output directory (default: .cache/converted/)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    converted_count = 0
    errors = []

    def process(body_path: Path, meta: dict) -> None:
        nonlocal converted_count
        result = convert_cached(body_path, meta, args.out, args.format)
        if result:
            converted_count += 1
        else:
            errors.append(str(body_path))

    if args.input:
        inp = args.input
        if inp.suffix == ".body":
            body_path = inp
            meta_path = inp.with_suffix(".meta.json")
        else:
            body_path = inp.with_suffix(".body")
            meta_path = inp.with_suffix(".meta.json")

        if not body_path.exists():
            sys.exit(f"Body file not found: {body_path}")

        meta = {}
        if meta_path.exists():
            with meta_path.open() as f:
                meta = json.load(f)
        process(body_path, meta)

    elif args.sidecar:
        with args.sidecar.open(encoding="utf-8") as f:
            sidecar = json.load(f)
        for src in sidecar.get("sources", []):
            url = src.get("canonical_url", "")
            if not url:
                continue
            body_path, meta = cache_entry_for_url(url)
            if body_path is None:
                log.warning("No cache entry for %s — run fetch_sources.py first", url)
                continue
            process(body_path, meta)

    else:  # --all
        for meta_path in sorted(CACHE_DIR.rglob("*.meta.json")):
            body_path = meta_path.with_suffix(".body")
            if not body_path.exists():
                continue
            try:
                with meta_path.open() as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
            process(body_path, meta)

    print(f"\nConverted: {converted_count} files → {args.out}")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  {e}")
    print("\nREMINDER: All output is UNTRUSTED EVIDENCE.")
    print("Write original Markdown summaries — do not paste converted text directly into resources/.")


if __name__ == "__main__":
    main()
