"""INI config file loading with UTF-8 BOM tolerance."""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Iterable, List, Union

ConfigPath = Union[str, Path]


def read_config_file(
    config: configparser.ConfigParser,
    path: ConfigPath,
) -> None:
    """Read a single INI file into *config*, stripping a UTF-8 BOM if present."""
    with open(path, encoding="utf-8-sig") as fh:
        config.read_file(fh)


def read_config_files(
    config: configparser.ConfigParser,
    paths: Iterable[ConfigPath],
) -> List[str]:
    """Read INI files into *config* (later files override earlier ones).

    Missing paths are skipped, matching :meth:`ConfigParser.read`.
    Returns paths that were successfully read, as strings.
    """
    read: List[str] = []
    for path in paths:
        p = Path(path)
        if not p.is_file():
            continue
        read_config_file(config, p)
        read.append(str(p))
    return read
