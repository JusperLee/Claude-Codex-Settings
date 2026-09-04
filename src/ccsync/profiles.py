from __future__ import annotations

import re


PORTABLE_PATHS = (
    ".codex/AGENTS.md",
    ".codex/instructions.md",
    ".codex/rules/",
    ".codex/skills/",
    ".codex/statusline/",
    ".codex/statusline.sh",
    ".codex/statusline.py",
    ".claude/CLAUDE.md",
    ".claude/agents/",
    ".claude/commands/",
    ".claude/hooks/",
    ".claude/skills/",
    ".claude/plugins/installed_plugins.json",
    ".claude/plugins/known_marketplaces.json",
    ".claude/statusline/",
    ".claude/statusline.sh",
    ".claude/statusline.py",
)

HISTORY_PATHS = (
    ".codex/sessions/",
    ".codex/archived_sessions/",
    ".codex/generated_images/",
    ".claude/projects/",
    ".claude/history.jsonl",
)

SPECIAL_PATHS = (
    ".codex/config.toml",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude.json",
)

SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


def normalize_path(path: str) -> str:
    directory = path.endswith("/")
    clean = path.strip()
    if clean.startswith("./"):
        clean = clean[2:]
    clean = clean.rstrip("/")
    if not clean or clean.startswith(("/", "~")) or ".." in clean.split("/") or not SAFE_PATH.fullmatch(clean):
        raise ValueError(f"Path must be relative to HOME: {path}")
    return clean + ("/" if directory else "")


def sync_paths(with_history: bool, extra_paths: list[str]) -> list[str]:
    paths = list(PORTABLE_PATHS)
    if with_history:
        paths.extend(HISTORY_PATHS)
    paths.extend(normalize_path(path) for path in extra_paths)
    return list(dict.fromkeys(paths))
