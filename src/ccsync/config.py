from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


DEFAULT_CREDENTIAL_PATHS = [
    ".codex/auth.json",
    ".claude/.credentials.json",
]
REMOTE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
REMOTE_TARGET = re.compile(r"^[A-Za-z0-9_.@:-]+$")


def default_config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "ccsync" / "config.json"


@dataclass(frozen=True)
class Remote:
    name: str
    target: str
    port: int | None = None
    identity_file: str | None = None

    def __post_init__(self) -> None:
        if not REMOTE_NAME.fullmatch(self.name):
            raise ValueError(f"Invalid remote name: {self.name}")
        if not REMOTE_TARGET.fullmatch(self.target):
            raise ValueError(f"Invalid SSH target: {self.target}")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError(f"Invalid SSH port: {self.port}")


@dataclass
class AppConfig:
    remotes: dict[str, Remote] = field(default_factory=dict)
    extra_paths: list[str] = field(default_factory=list)
    credential_paths: list[str] = field(default_factory=lambda: list(DEFAULT_CREDENTIAL_PATHS))


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    if not config_path.exists():
        return AppConfig()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    remotes = {
        name: Remote(name=name, **{key: value for key, value in value.items() if key != "name"})
        for name, value in raw.get("remotes", {}).items()
    }
    return AppConfig(
        remotes=remotes,
        extra_paths=list(raw.get("extra_paths", [])),
        credential_paths=list(raw.get("credential_paths", DEFAULT_CREDENTIAL_PATHS)),
    )


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "remotes": {name: asdict(remote) for name, remote in sorted(config.remotes.items())},
        "extra_paths": config.extra_paths,
        "credential_paths": config.credential_paths,
    }
    temporary = config_path.with_name(f".{config_path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, config_path)
    return config_path
