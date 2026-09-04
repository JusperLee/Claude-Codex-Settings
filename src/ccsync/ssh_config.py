from __future__ import annotations

import glob
import shlex
from pathlib import Path

from .config import REMOTE_NAME, REMOTE_TARGET


WILDCARD_CHARACTERS = "*?![]"


def _include_paths(pattern: str, source: Path) -> list[Path]:
    expanded = pattern.replace("%d", str(Path.home()))
    candidate = Path(expanded).expanduser()
    if not candidate.is_absolute():
        candidate = source.parent / candidate
    return [Path(match) for match in sorted(glob.glob(str(candidate)))]


def read_ssh_hosts(path: Path | None = None) -> list[str]:
    config_path = (path or Path.home() / ".ssh" / "config").expanduser()
    hosts: list[str] = []
    visited: list[Path] = []

    def read_file(source: Path) -> None:
        resolved = source.resolve()
        if resolved in visited or not resolved.is_file():
            return
        visited.append(resolved)
        for line in resolved.read_text(encoding="utf-8").splitlines():
            words = shlex.split(line, comments=True, posix=True)
            if not words:
                continue
            keyword = words[0].lower()
            if keyword == "include":
                for pattern in words[1:]:
                    for included in _include_paths(pattern, resolved):
                        read_file(included)
            elif keyword == "host":
                for host in words[1:]:
                    concrete = not any(character in host for character in WILDCARD_CHARACTERS)
                    valid = REMOTE_NAME.fullmatch(host) and REMOTE_TARGET.fullmatch(host)
                    if concrete and valid and host not in hosts:
                        hosts.append(host)

    read_file(config_path)
    return hosts
