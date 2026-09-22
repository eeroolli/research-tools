"""Add a searchable Tesseract text layer to a PDF via ocrmypdf.

Original page images stay. Output is a sibling ``*_ocr.pdf`` by default;
the source file is never overwritten.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

_TEXT_MODE_FLAGS = {
    "skip": "--skip-text",
    "redo": "--redo-ocr",
    "force": "--force-ocr",
}
_GS_NAMES = ("gs", "gswin64c", "gswin32c")
_REQUIRED = ("ocrmypdf", "tesseract")
_EOL_HYPHEN = re.compile(r"-\r?\n")


class TextLayerError(RuntimeError):
    """OCR text-layer failure."""


class MissingDependencyError(TextLayerError):
    """A required binary is not on PATH."""


def language_codes(language: str) -> List[str]:
    """Split ocrmypdf ``--language`` values (``eng``, ``eng+nld``)."""
    return [part for part in re.split(r"[+\s,]+", language.strip()) if part]


def _tessdata_candidates() -> List[Path]:
    candidates: List[Path] = []
    env_prefix = os.environ.get("TESSDATA_PREFIX")
    if env_prefix:
        candidates.append(Path(env_prefix))
    tess_bin = shutil.which("tesseract")
    if tess_bin:
        bindir = Path(tess_bin).resolve().parent
        for root in (bindir.parent.parent, bindir.parent):
            candidates.extend(
                (
                    root / "share" / "tessdata",
                    root / "Library" / "share" / "tessdata",
                )
            )
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        root = Path(conda_prefix)
        candidates.extend(
            (
                root / "share" / "tessdata",
                root / "Library" / "share" / "tessdata",
            )
        )
    seen = set()
    out: List[Path] = []
    for raw in candidates:
        for path in (raw, raw / "tessdata"):
            resolved = path.resolve() if path.exists() else path
            if resolved in seen:
                continue
            seen.add(resolved)
            out.append(path)
    return out


def find_tessdata_dir() -> Optional[Path]:
    """Directory that contains ``*.traineddata``, or None."""
    for path in _tessdata_candidates():
        if (path / "eng.traineddata").is_file() or any(path.glob("*.traineddata")):
            return path
    return None


def find_tessdata_config_dir() -> Optional[Path]:
    """Directory whose ``configs/hocr`` exists (conda Windows may split this)."""
    for path in _tessdata_candidates():
        if (path / "configs" / "hocr").is_file():
            return path
    return None


def merge_tessdata_configs(lang_dir: Path, config_root: Path) -> None:
    """Copy Tesseract ``configs`` into the language dir if missing.

    conda-forge Windows puts ``*.traineddata`` in ``share/tessdata`` and
    ``configs/hocr`` in ``Library/share/tessdata``. Tesseract needs both
    under TESSDATA_PREFIX.
    """
    for name in ("configs", "tessconfigs"):
        src = config_root / name
        dest = lang_dir / name
        if not src.is_dir() or (dest / "hocr").is_file():
            continue
        shutil.copytree(src, dest, dirs_exist_ok=True)


def prepare_tessdata_dir() -> Optional[Path]:
    """Return a tessdata dir that has language files, merging configs if split."""
    lang_dir = find_tessdata_dir()
    if lang_dir is None:
        return None
    if not (lang_dir / "configs" / "hocr").is_file():
        config_root = find_tessdata_config_dir()
        if config_root is not None and config_root.resolve() != lang_dir.resolve():
            logger.info(
                "Copying Tesseract configs from %s into %s", config_root, lang_dir
            )
            merge_tessdata_configs(lang_dir, config_root)
    return lang_dir


def language_data_present(tessdata_dir: Path, language: str = "eng") -> bool:
    return all(
        (tessdata_dir / f"{code}.traineddata").is_file()
        for code in language_codes(language)
    )


def join_eol_hyphens(text: str) -> str:
    """Join end-of-line hyphens only (``occur-\\nring`` → ``occurring``)."""
    return _EOL_HYPHEN.sub("", text)


def default_output_path(input_pdf: PathLike) -> Path:
    path = Path(input_pdf)
    return path.parent / f"{path.stem}_ocr.pdf"


def check_dependencies(*, require_unpaper: bool = False, language: str = "eng") -> None:
    """Fail clearly if ocrmypdf, tesseract, Ghostscript, or tessdata are missing.

    ``unpaper`` is checked only when ``require_unpaper`` is true (``--clean``).
    """
    missing = [name for name in _REQUIRED if not shutil.which(name)]
    if not any(shutil.which(name) for name in _GS_NAMES):
        missing.append("gs")
    if missing:
        raise MissingDependencyError(
            "Missing required binaries: "
            + ", ".join(missing)
            + ". Install with: conda install -c conda-forge ocrmypdf tesseract ghostscript "
            "(env research-tools / research-tools-win, or put them on PATH for .venv-win)."
        )
    tessdata = find_tessdata_dir()
    if tessdata is None or not language_data_present(tessdata, language):
        codes = ", ".join(f"{code}.traineddata" for code in language_codes(language))
        raise MissingDependencyError(
            "Tesseract language data not found "
            f"({codes}). Set TESSDATA_PREFIX to the directory that contains those files "
            "(conda-forge: $CONDA_PREFIX/share/tessdata), or reinstall tesseract: "
            "conda install -c conda-forge tesseract."
        )
    if require_unpaper and not shutil.which("unpaper"):
        raise MissingDependencyError(
            "unpaper is required for --clean but was not found on PATH. "
            "Install it in WSL research-tools (conda install -c conda-forge unpaper, "
            "or sudo apt install unpaper). Do not omit --clean silently."
        )


def build_ocrmypdf_argv(
    input_pdf: PathLike,
    output_pdf: PathLike,
    *,
    language: str = "eng",
    oversample: int = 300,
    deskew: bool = True,
    clean: bool = False,
    rotate: bool = False,
    text_mode: str = "skip",
    pages: Optional[str] = None,
) -> List[str]:
    """Build the ocrmypdf command. Does not run it."""
    flag = _TEXT_MODE_FLAGS.get(text_mode)
    if flag is None:
        raise ValueError(
            f"text_mode must be one of {sorted(_TEXT_MODE_FLAGS)}, got {text_mode!r}"
        )
    if text_mode == "redo" and (deskew or clean):
        raise TextLayerError(
            "--redo-ocr cannot be combined with --deskew or --clean "
            "(ocrmypdf limitation). Use --no-deskew with --redo-ocr, "
            "or --force-ocr if you need deskew (rasterizes every page)."
        )
    argv = [
        "ocrmypdf",
        "--language",
        language,
        "--output-type",
        "pdf",
        "--oversample",
        str(oversample),
        flag,
    ]
    if deskew:
        argv.append("--deskew")
    if clean:
        argv.append("--clean")
    if rotate:
        argv.append("--rotate-pages")
    if pages:
        argv.extend(["--pages", pages])
    argv.extend([str(input_pdf), str(output_pdf)])
    return argv


def write_txt_sidecar(pdf_path: PathLike) -> Path:
    """Extract text from a PDF and write ``{stem}.txt`` with hyphen join."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise TextLayerError(
            "pymupdf is required for --txt sidecar extraction"
        ) from exc

    path = Path(pdf_path)
    doc = fitz.open(path)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    sidecar = path.with_suffix(".txt")
    sidecar.write_text(join_eol_hyphens(text), encoding="utf-8")
    return sidecar


def add_text_layer(
    input_pdf: PathLike,
    output_pdf: Optional[PathLike] = None,
    *,
    language: str = "eng",
    oversample: int = 300,
    deskew: bool = True,
    clean: bool = False,
    rotate: bool = False,
    text_mode: str = "skip",
    pages: Optional[str] = None,
    write_txt: bool = False,
) -> Path:
    """Run ocrmypdf so the output PDF has a searchable text layer.

    Returns the output path. Never overwrites the input file.
    """
    source = Path(input_pdf)
    if not source.is_file():
        raise FileNotFoundError(f"Input PDF not found: {source}")

    dest = Path(output_pdf) if output_pdf is not None else default_output_path(source)
    if dest.resolve() == source.resolve():
        raise TextLayerError(
            f"Refusing to overwrite the source PDF: {source}. "
            "Choose a different -o path (default is a sibling *_ocr.pdf)."
        )

    check_dependencies(require_unpaper=clean, language=language)
    argv = build_ocrmypdf_argv(
        source,
        dest,
        language=language,
        oversample=oversample,
        deskew=deskew,
        clean=clean,
        rotate=rotate,
        text_mode=text_mode,
        pages=pages,
    )
    env = os.environ.copy()
    tessdata = prepare_tessdata_dir()
    if tessdata is not None:
        env["TESSDATA_PREFIX"] = str(tessdata)
        logger.info("TESSDATA_PREFIX=%s", tessdata)
    logger.info("Running: %s", " ".join(argv))
    result = subprocess.run(
        argv, capture_output=True, text=True, check=False, env=env
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise TextLayerError(
            f"ocrmypdf failed with exit {result.returncode}"
            + (f": {detail}" if detail else "")
        )

    if write_txt:
        write_txt_sidecar(dest)
    return dest
