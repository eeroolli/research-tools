"""Tests for BOM-tolerant config file loading."""

import configparser
from pathlib import Path

from shared_tools.config.io import read_config_file, read_config_files


def test_read_config_file_strips_utf8_bom(tmp_path: Path) -> None:
    config_path = tmp_path / "config.conf"
    config_path.write_bytes(b"\xef\xbb\xbf[PATHS]\nkey = value\n")

    config = configparser.ConfigParser()
    read_config_file(config, config_path)

    assert config.has_section("PATHS")
    assert config.get("PATHS", "key") == "value"


def test_read_config_files_skips_missing(tmp_path: Path) -> None:
    present = tmp_path / "config.conf"
    present.write_text("[MAIN]\noption = yes\n", encoding="utf-8")

    config = configparser.ConfigParser()
    read = read_config_files(
        config,
        [present, tmp_path / "missing.conf"],
    )

    assert read == [str(present)]
    assert config.get("MAIN", "option") == "yes"
