"""Tests for OCR text-layer helper (mocked ocrmypdf; no Tesseract in CI)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from shared_tools.pdf.text_layer import (
    MissingDependencyError,
    TextLayerError,
    add_text_layer,
    build_ocrmypdf_argv,
    check_dependencies,
    join_eol_hyphens,
)


def _make_pdf(path: Path, text: str = "hello") -> Path:
    try:
        import fitz
    except ImportError as exc:
        pytest.skip(f"PyMuPDF not available: {exc}")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(page.rect, text)
    doc.save(str(path))
    doc.close()
    return path


def _patch_which(monkeypatch, *, missing=(), unpaper=True, tessdata=True):
    missing = set(missing)

    def fake_which(name: str):
        base = Path(name).name.lower().replace(".exe", "")
        if base in missing:
            return None
        if base in ("gs", "gswin64c", "gswin32c"):
            return None if "gs" in missing else "/fake/gs"
        if base == "unpaper":
            return "/fake/unpaper" if unpaper else None
        return f"/fake/{base}"

    monkeypatch.setattr("shared_tools.pdf.text_layer.shutil.which", fake_which)
    if tessdata:
        fake_dir = Path("/fake/tessdata")
        monkeypatch.setattr(
            "shared_tools.pdf.text_layer.find_tessdata_dir", lambda: fake_dir
        )
        monkeypatch.setattr(
            "shared_tools.pdf.text_layer.find_tessdata_config_dir", lambda: None
        )
        monkeypatch.setattr(
            "shared_tools.pdf.text_layer.language_data_present",
            lambda *_args, **_kwargs: True,
        )
    else:
        monkeypatch.setattr(
            "shared_tools.pdf.text_layer.find_tessdata_dir", lambda: None
        )


def _patch_run(monkeypatch, captured, *, copy_input=False):
    def fake_run(argv, capture_output=True, text=True, check=False, env=None):
        captured.append({"argv": list(argv), "env": env})
        dest = Path(argv[-1])
        src = Path(argv[-2])
        if copy_input and src.is_file():
            shutil.copy(src, dest)
        else:
            dest.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("shared_tools.pdf.text_layer.subprocess.run", fake_run)


def test_join_eol_hyphens():
    assert join_eol_hyphens("occur-\nring") == "occurring"
    assert join_eol_hyphens("occur-\r\nring") == "occurring"


def test_refuses_to_overwrite_input(tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(TextLayerError, match="overwrite"):
        add_text_layer(pdf, pdf)
    with pytest.raises(TextLayerError, match="overwrite"):
        add_text_layer(pdf, tmp_path / "book.pdf")


def test_default_argv(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    captured: list[list[str]] = []
    _patch_which(monkeypatch)
    _patch_run(monkeypatch, captured)
    add_text_layer(pdf)
    argv = captured[0]["argv"]
    assert argv[0] == "ocrmypdf"
    assert argv[argv.index("--oversample") + 1] == "300"
    assert "--skip-text" in argv
    assert argv[argv.index("--output-type") + 1] == "pdf"
    assert "--deskew" in argv
    assert "--clean" not in argv
    assert "--rotate-pages" not in argv
    assert argv[-1].endswith("scan_ocr.pdf")


def test_flag_variants(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    captured: list[list[str]] = []
    _patch_which(monkeypatch)
    _patch_run(monkeypatch, captured)

    add_text_layer(pdf, tmp_path / "a.pdf", clean=True, rotate=True)
    add_text_layer(pdf, tmp_path / "b.pdf", text_mode="redo", deskew=False)
    add_text_layer(pdf, tmp_path / "c.pdf", text_mode="force")
    add_text_layer(pdf, tmp_path / "d.pdf", pages="1-3")

    clean_argv = captured[0]["argv"]
    redo_argv = captured[1]["argv"]
    force_argv = captured[2]["argv"]
    pages_argv = captured[3]["argv"]
    assert "--clean" in clean_argv
    assert "--rotate-pages" in clean_argv
    assert "--redo-ocr" in redo_argv
    assert "--deskew" not in redo_argv
    assert "--skip-text" not in redo_argv
    assert "--force-ocr" in force_argv
    assert "--skip-text" not in force_argv
    assert pages_argv[pages_argv.index("--pages") + 1] == "1-3"


def test_txt_hyphen_join(tmp_path, monkeypatch):
    pdf = _make_pdf(tmp_path / "hyphen.pdf", "occur-\nring")
    captured: list[list[str]] = []
    _patch_which(monkeypatch)
    _patch_run(monkeypatch, captured, copy_input=True)
    out = add_text_layer(pdf, write_txt=True)
    sidecar = out.with_suffix(".txt")
    assert sidecar.is_file()
    assert "occurring" in sidecar.read_text(encoding="utf-8")


def test_missing_required_binaries(monkeypatch):
    for name in ("ocrmypdf", "tesseract", "gs"):
        _patch_which(monkeypatch, missing={name})
        with pytest.raises(MissingDependencyError, match=name):
            check_dependencies()


def test_unpaper_required_only_for_clean(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    _patch_which(monkeypatch, unpaper=False)
    check_dependencies()
    with pytest.raises(MissingDependencyError, match="unpaper"):
        check_dependencies(require_unpaper=True)
    with pytest.raises(MissingDependencyError, match="unpaper"):
        add_text_layer(pdf, clean=True)
    captured: list[list[str]] = []
    _patch_run(monkeypatch, captured)
    add_text_layer(pdf)
    assert "--clean" not in captured[0]["argv"]


def test_build_argv_no_deskew():
    argv = build_ocrmypdf_argv("in.pdf", "out.pdf", deskew=False)
    assert "--deskew" not in argv
    assert "--skip-text" in argv


def test_redo_rejects_deskew_and_clean():
    with pytest.raises(TextLayerError, match="cannot be combined"):
        build_ocrmypdf_argv("in.pdf", "out.pdf", text_mode="redo", deskew=True)
    with pytest.raises(TextLayerError, match="cannot be combined"):
        build_ocrmypdf_argv(
            "in.pdf", "out.pdf", text_mode="redo", deskew=False, clean=True
        )
    argv = build_ocrmypdf_argv("in.pdf", "out.pdf", text_mode="redo", deskew=False)
    assert "--redo-ocr" in argv
    assert "--deskew" not in argv


def test_missing_tessdata(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    _patch_which(monkeypatch, tessdata=False)
    with pytest.raises(MissingDependencyError, match="language data"):
        add_text_layer(pdf)


def test_tessdata_prefix_injected(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    captured: list[dict] = []
    _patch_which(monkeypatch)
    _patch_run(monkeypatch, captured)
    add_text_layer(pdf)
    assert captured[0]["env"]["TESSDATA_PREFIX"] == os.fspath(Path("/fake/tessdata"))


def test_merge_tessdata_configs(tmp_path):
    from shared_tools.pdf.text_layer import merge_tessdata_configs

    lang = tmp_path / "langs"
    lang.mkdir()
    (lang / "eng.traineddata").write_bytes(b"x")
    config_root = tmp_path / "cfg"
    (config_root / "configs").mkdir(parents=True)
    (config_root / "configs" / "hocr").write_text("tessedit_create_hocr 1\n")
    merge_tessdata_configs(lang, config_root)
    assert (lang / "configs" / "hocr").is_file()
