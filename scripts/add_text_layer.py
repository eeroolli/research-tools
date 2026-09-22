#!/usr/bin/env python3
"""Add a searchable OCR text layer to a PDF via ocrmypdf (Tesseract).

Default output is a sibling ``{stem}_ocr.pdf``. Never overwrites the source.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from shared_tools.pdf.text_layer import (  # noqa: E402
    TextLayerError,
    add_text_layer,
)

logger = logging.getLogger(__name__)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Add a searchable Tesseract text layer with ocrmypdf. "
            "Original page images stay; output is a sibling *_ocr.pdf by default."
        )
    )
    parser.add_argument("input_pdf", type=Path, help="Input PDF")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output PDF (default: INPUT_ocr.pdf next to the input)",
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="ocrmypdf --pages range (e.g. 1-3 or 1,12,30); does not slice the file",
    )
    parser.add_argument("--language", default="eng", help="Tesseract language (default: eng)")
    parser.add_argument(
        "--oversample",
        type=int,
        default=300,
        help="Rasterize at this DPI for OCR (default: 300)",
    )
    deskew = parser.add_mutually_exclusive_group()
    parser.set_defaults(deskew=None)
    deskew.add_argument(
        "--deskew",
        action="store_true",
        help="Deskew pages (default except with --redo-ocr)",
    )
    deskew.add_argument(
        "--no-deskew",
        action="store_false",
        dest="deskew",
        help="Disable deskew",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Run unpaper before OCR (off by default; fails if unpaper is missing)",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Enable ocrmypdf --rotate-pages (off by default; OSD can flip a whole book)",
    )
    ocr_mode = parser.add_mutually_exclusive_group()
    ocr_mode.add_argument(
        "--redo-ocr",
        action="store_true",
        help=(
            "Replace existing OCR-looking text "
            "(incompatible with --deskew; use --force-ocr to deskew)"
        ),
    )
    ocr_mode.add_argument(
        "--force-ocr",
        action="store_true",
        help="Rasterize and OCR every page",
    )
    parser.add_argument(
        "--txt",
        action="store_true",
        help="After a successful write, dump hyphen-joined text to {output.stem}.txt",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.force_ocr:
        text_mode = "force"
    elif args.redo_ocr:
        text_mode = "redo"
    else:
        text_mode = "skip"
    if args.deskew is None:
        deskew = text_mode != "redo"
    else:
        deskew = args.deskew
    try:
        out = add_text_layer(
            args.input_pdf,
            args.output,
            language=args.language,
            oversample=args.oversample,
            deskew=deskew,
            clean=args.clean,
            rotate=args.rotate,
            text_mode=text_mode,
            pages=args.pages,
            write_txt=args.txt,
        )
    except (TextLayerError, FileNotFoundError) as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
