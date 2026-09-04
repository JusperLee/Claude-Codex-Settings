from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, Remote
from .merge import merge_json_values, merge_toml_text
from .profiles import SPECIAL_PATHS, normalize_path, sync_paths


def ssh_transport(remote: Remote) -> list[str]:
    command = ["ssh"]
    if remote.port is not None:
        command.extend(["-p", str(remote.port)])
    if remote.identity_file:
        command.extend(["-i", remote.identity_file])
    return command


def ssh_command(remote: Remote, remote_command: str) -> list[str]:
    return [*ssh_transport(remote), remote.target, remote_command]


def rsync_command(remote: Remote, options: list[str], source: str, destination: str) -> list[str]:
    return ["rsync", *options, "-e", shlex.join(ssh_transport(remote)), source, destination]


def build_filters(paths: list[str] | tuple[str, ...]) -> list[str]:
    includes: list[str] = []
    for raw_path in paths:
        path = normalize_path(raw_path)
        clean = path.rstrip("/")
        parts = clean.split("/")
        for index in range(1, len(parts)):
            includes.append(f"--include=/{'/'.join(parts[:index])}/")
        if path.endswith("/"):
            includes.append(f"--include=/{clean}/***")
        else:
            includes.append(f"--include=/{clean}")
    return [*dict.fromkeys(includes), "--exclude=*"]


def _run(command: list[str]) -> None:
    print("$", shlex.join(command))
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def _state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "ccsync"


def _backup_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_options(directory: str) -> list[str]:
    return ["--backup", f"--backup-dir={directory}"]


def _sync_regular_paths(
    remote: Remote, paths: list[str], *, dry_run: bool, stamp: str
) -> None:
    options = ["-azu", "--itemize-changes", "--prune-empty-dirs", *build_filters(paths)]
    if dry_run:
        options.insert(1, "--dry-run")
        pull_options = options
        push_options = options
    else:
        local_backup = _state_root() / "backups" / remote.name / stamp / "local"
        local_backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        pull_options = [*options, *_backup_options(str(local_backup))]
        remote_backup = f".local/state/ccsync/backups/{remote.name}/{stamp}/remote"
        push_options = [*options, *_backup_options(remote_backup)]

    local_home = f"{Path.home()}/"
    remote_home = f"{remote.target}:~/"
    print(f"[{remote.name}] remote -> local")
    _run(rsync_command(remote, pull_options, remote_home, local_home))
    print(f"[{remote.name}] local -> remote")
    _run(rsync_command(remote, push_options, local_home, remote_home))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0


def _write_private(path: Path, content: str, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    os.utime(path, (mtime, mtime))


def _backup_local_file(path: Path, backup_root: Path) -> None:
    if path.exists():
        destination = backup_root / path.relative_to(Path.home())
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(path, destination)
        destination.chmod(0o600)


def _special_action(local: Path, remote_copy: Path) -> str:
    if not local.exists():
        return "download"
    if not remote_copy.exists():
        return "upload"
    if _mtime(remote_copy) == _mtime(local):
        return "unchanged"
    return "download" if _mtime(remote_copy) > _mtime(local) else "upload"


def _merge_special_files(
    remote: Remote, *, dry_run: bool, stamp: str
) -> None:
    with tempfile.TemporaryDirectory(prefix="ccsync-") as directory:
        stage = Path(directory)
        fetch_options = ["-az", "--relative", "--prune-empty-dirs", *build_filters(SPECIAL_PATHS)]
        _run(rsync_command(remote, fetch_options, f"{remote.target}:~/", f"{stage}/"))
        backup_root = _state_root() / "backups" / remote.name / stamp / "local"
        changed = False

        for relative in SPECIAL_PATHS:
            local = Path.home() / relative
            remote_copy = stage / relative
            if not local.exists() and not remote_copy.exists():
                continue
            action = _special_action(local, remote_copy)
            print(f"[{remote.name}] {action}: ~/{relative} (machine-local secrets preserved)")
            if dry_run or action == "unchanged":
                continue

            prefer_remote = remote_copy.exists() and _mtime(remote_copy) >= _mtime(local)
            selected_mtime = max(_mtime(local), _mtime(remote_copy), 1)
            if relative.endswith(".json"):
                local_value = _read_json(local)
                remote_value = _read_json(remote_copy)
                local_value, remote_value = merge_json_values(
                    local_value, remote_value, prefer_remote=prefer_remote
                )
                local_content = json.dumps(local_value, ensure_ascii=False, indent=2) + "\n"
                remote_content = json.dumps(remote_value, ensure_ascii=False, indent=2) + "\n"
            else:
                local_content, remote_content = merge_toml_text(
                    _read_text(local), _read_text(remote_copy), prefer_remote=prefer_remote
                )

            _backup_local_file(local, backup_root)
            _write_private(local, local_content, selected_mtime)
            _write_private(remote_copy, remote_content, selected_mtime)
            changed = True

        if changed:
            remote_backup = f".local/state/ccsync/backups/{remote.name}/{stamp}/remote"
            upload_options = [
                "-az",
                "--ignore-times",
                "--relative",
                "--prune-empty-dirs",
                *build_filters(SPECIAL_PATHS),
                *_backup_options(remote_backup),
            ]
            _run(rsync_command(remote, upload_options, f"{stage}/", f"{remote.target}:~/"))


def _bootstrap_credentials(
    remote: Remote, credential_paths: list[str], *, dry_run: bool
) -> None:
    for raw_path in credential_paths:
        relative = normalize_path(raw_path)
        local = Path.home() / relative
        if not local.is_file():
            continue
        print(f"[{remote.name}] initialize credential if missing: ~/{relative}")
        if dry_run:
            continue
        options = ["-az", "--ignore-existing", "--itemize-changes"]
        _run(
            rsync_command(
                remote,
                options,
                str(local),
                f"{remote.target}:~/{relative}",
            )
        )


def sync_remote(
    config: AppConfig,
    remote: Remote,
    *,
    with_history: bool = False,
    dry_run: bool = False,
) -> None:
    stamp = _backup_stamp()
    if not dry_run:
        directories = {
            str(Path(path).parent)
            for path in config.credential_paths
            if str(Path(path).parent) != "."
        }
        directories.update({".codex", ".claude", f".local/state/ccsync/backups/{remote.name}/{stamp}/remote"})
        remote_directories = " ".join(f"~/{normalize_path(path)}" for path in sorted(directories))
        _run(ssh_command(remote, f"mkdir -p {remote_directories}"))
    _merge_special_files(remote, dry_run=dry_run, stamp=stamp)
    _sync_regular_paths(
        remote,
        sync_paths(with_history, config.extra_paths),
        dry_run=dry_run,
        stamp=stamp,
    )
    _bootstrap_credentials(remote, config.credential_paths, dry_run=dry_run)
    if not dry_run:
        _run(ssh_command(remote, "chmod -R go-rwx ~/.local/state/ccsync"))
