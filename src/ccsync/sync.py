from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import AppConfig, Remote
from .merge import merge_json_values, merge_toml_text
from .profiles import SPECIAL_PATHS, normalize_path, sync_paths


@dataclass(frozen=True)
class SyncFailure:
    step: str
    return_code: int | None
    message: str


@dataclass
class SyncReport:
    remote: str
    failures: list[SyncFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


@dataclass
class _SyncContext:
    config: AppConfig
    remote: Remote
    stage: Path
    stamp: str
    paths: list[str]
    report: SyncReport
    special_ready: bool = False
    special_merged: bool = False
    special_upload_needed: bool = False
    regular_pull_ok: bool = False


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


def _run(command: list[str], context: _SyncContext, step: str) -> bool:
    print(f"[{context.remote.name}] $ {shlex.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode:
        context.report.failures.append(
            SyncFailure(step, result.returncode, f"{command[0]} returned {result.returncode}")
        )
        return False
    return True


def _state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "ccsync"


def _backup_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_options(directory: str) -> list[str]:
    return ["--backup", f"--backup-dir={directory}"]


def _regular_options(context: _SyncContext, *, dry_run: bool) -> list[str]:
    options = [
        "-azu",
        "--itemize-changes",
        f"--out-format=[{context.remote.name}] %i %n%L",
        "--prune-empty-dirs",
        *build_filters(context.paths),
    ]
    if dry_run:
        options.insert(1, "--dry-run")
    return options


def _pull_regular(context: _SyncContext, *, dry_run: bool = False) -> bool:
    options = _regular_options(context, dry_run=dry_run)
    if not dry_run:
        local_backup = _state_root() / "backups" / context.remote.name / context.stamp / "local"
        local_backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        options.extend(_backup_options(str(local_backup)))
    print(f"[{context.remote.name}] remote -> local")
    result = _run(
        rsync_command(
            context.remote,
            options,
            f"{context.remote.target}:~/",
            f"{Path.home()}/",
        ),
        context,
        "pull settings",
    )
    if not dry_run:
        context.regular_pull_ok = result
    return result


def _push_regular(context: _SyncContext, *, dry_run: bool = False) -> bool:
    options = _regular_options(context, dry_run=dry_run)
    if not dry_run:
        remote_backup = (
            f".local/state/ccsync/backups/{context.remote.name}/{context.stamp}/remote"
        )
        options.extend(_backup_options(remote_backup))
    print(f"[{context.remote.name}] local -> remote")
    return _run(
        rsync_command(
            context.remote,
            options,
            f"{Path.home()}/",
            f"{context.remote.target}:~/",
        ),
        context,
        "push settings",
    )


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


def _merged_special_content(
    local: Path, remote_copy: Path, *, prefer_remote: bool
) -> tuple[str, str]:
    if local.name.endswith(".json"):
        local_value, remote_value = merge_json_values(
            _read_json(local),
            _read_json(remote_copy),
            prefer_remote=prefer_remote,
        )
        return (
            json.dumps(local_value, ensure_ascii=False, indent=2) + "\n",
            json.dumps(remote_value, ensure_ascii=False, indent=2) + "\n",
        )
    return merge_toml_text(
        _read_text(local),
        _read_text(remote_copy),
        prefer_remote=prefer_remote,
    )


def _fetch_special(context: _SyncContext) -> bool:
    options = ["-az", "--relative", "--prune-empty-dirs", *build_filters(SPECIAL_PATHS)]
    context.special_ready = _run(
        rsync_command(
            context.remote,
            options,
            f"{context.remote.target}:~/",
            f"{context.stage}/",
        ),
        context,
        "fetch mixed settings",
    )
    return context.special_ready


def _show_special_status(context: _SyncContext) -> None:
    if not context.special_ready:
        return
    for relative in SPECIAL_PATHS:
        local = Path.home() / relative
        remote_copy = context.stage / relative
        if local.exists() or remote_copy.exists():
            action = _special_action(local, remote_copy)
            print(
                f"[{context.remote.name}] {action}: ~/{relative} "
                "(machine-local secrets preserved)"
            )


def _merge_special_to_local(context: _SyncContext) -> None:
    if not context.special_ready:
        return
    backup_root = (
        _state_root() / "backups" / context.remote.name / context.stamp / "local"
    )
    for relative in SPECIAL_PATHS:
        local = Path.home() / relative
        remote_copy = context.stage / relative
        if not local.exists() and not remote_copy.exists():
            continue
        action = _special_action(local, remote_copy)
        print(
            f"[{context.remote.name}] {action}: ~/{relative} "
            "(machine-local secrets preserved)"
        )
        if action == "unchanged":
            continue
        prefer_remote = remote_copy.exists() and _mtime(remote_copy) > _mtime(local)
        selected_mtime = max(_mtime(local), _mtime(remote_copy), 1)
        local_content, remote_content = _merged_special_content(
            local,
            remote_copy,
            prefer_remote=prefer_remote,
        )
        _backup_local_file(local, backup_root)
        _write_private(local, local_content, selected_mtime)
        _write_private(remote_copy, remote_content, selected_mtime)
        context.special_upload_needed = True
    context.special_merged = True


def _finalize_special(context: _SyncContext) -> None:
    if not context.special_ready or not context.special_merged:
        return
    for relative in SPECIAL_PATHS:
        local = Path.home() / relative
        remote_copy = context.stage / relative
        if not local.exists() and not remote_copy.exists():
            continue
        if remote_copy.exists() and _mtime(remote_copy) == _mtime(local):
            continue
        _, remote_content = _merged_special_content(
            local,
            remote_copy,
            prefer_remote=False,
        )
        selected_mtime = max(_mtime(local), _mtime(remote_copy), 1)
        _write_private(remote_copy, remote_content, selected_mtime)
        context.special_upload_needed = True


def _upload_special(context: _SyncContext) -> bool:
    if not context.special_merged or not context.special_upload_needed:
        return True
    remote_backup = (
        f".local/state/ccsync/backups/{context.remote.name}/{context.stamp}/remote"
    )
    options = [
        "-az",
        "--ignore-times",
        "--relative",
        "--prune-empty-dirs",
        *build_filters(SPECIAL_PATHS),
        *_backup_options(remote_backup),
    ]
    return _run(
        rsync_command(
            context.remote,
            options,
            f"{context.stage}/",
            f"{context.remote.target}:~/",
        ),
        context,
        "push mixed settings",
    )


def _bootstrap_credentials(context: _SyncContext, *, dry_run: bool) -> None:
    for raw_path in context.config.credential_paths:
        relative = normalize_path(raw_path)
        local = Path.home() / relative
        if not local.is_file():
            continue
        print(f"[{context.remote.name}] initialize credential if missing: ~/{relative}")
        if dry_run:
            continue
        _run(
            rsync_command(
                context.remote,
                ["-az", "--ignore-existing", "--itemize-changes"],
                str(local),
                f"{context.remote.target}:~/{relative}",
            ),
            context,
            "initialize credential",
        )


def _prepare_remote(context: _SyncContext) -> None:
    directories = {
        str(Path(path).parent)
        for path in context.config.credential_paths
        if str(Path(path).parent) != "."
    }
    directories.update(
        {
            ".codex",
            ".claude",
            f".local/state/ccsync/backups/{context.remote.name}/{context.stamp}/remote",
        }
    )
    remote_directories = " ".join(
        f"~/{normalize_path(path)}" for path in sorted(directories)
    )
    _run(
        ssh_command(context.remote, f"mkdir -p {remote_directories}"),
        context,
        "prepare remote",
    )
    _fetch_special(context)


def _status_remote(context: _SyncContext) -> None:
    _fetch_special(context)
    _show_special_status(context)
    _pull_regular(context, dry_run=True)
    _push_regular(context, dry_run=True)
    _bootstrap_credentials(context, dry_run=True)


def _push_remote(context: _SyncContext) -> None:
    _upload_special(context)
    if context.regular_pull_ok:
        _push_regular(context)
    else:
        print(f"[{context.remote.name}] skipped push: pull did not complete")
    _bootstrap_credentials(context, dry_run=False)
    _run(
        ssh_command(context.remote, "chmod -R go-rwx ~/.local/state/ccsync"),
        context,
        "secure backup permissions",
    )


def _collect_tasks(
    contexts: list[_SyncContext],
    worker: Callable[[_SyncContext], None],
    *,
    jobs: int,
    step: str,
) -> None:
    with ThreadPoolExecutor(max_workers=min(jobs, len(contexts))) as executor:
        tasks = [(executor.submit(worker, context), context) for context in contexts]
        for task, context in tasks:
            error = task.exception()
            if error is not None:
                context.report.failures.append(
                    SyncFailure(step, None, f"{type(error).__name__}: {error}")
                )


def sync_remotes(
    config: AppConfig,
    remotes: list[Remote],
    *,
    with_history: bool = False,
    dry_run: bool = False,
    jobs: int = 4,
) -> list[SyncReport]:
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    if not remotes:
        return []

    stamp = _backup_stamp()
    with tempfile.TemporaryDirectory(prefix="ccsync-") as directory:
        stage_root = Path(directory)
        contexts = [
            _SyncContext(
                config=config,
                remote=remote,
                stage=stage_root / remote.name,
                stamp=stamp,
                paths=sync_paths(with_history, config.extra_paths),
                report=SyncReport(remote.name),
            )
            for remote in remotes
        ]
        for context in contexts:
            context.stage.mkdir(parents=True, mode=0o700)

        if dry_run:
            _collect_tasks(contexts, _status_remote, jobs=jobs, step="status")
        else:
            _collect_tasks(contexts, _prepare_remote, jobs=jobs, step="prepare")
            _collect_tasks(contexts, _merge_special_to_local, jobs=1, step="merge settings")
            _collect_tasks(contexts, _pull_regular, jobs=1, step="pull settings")
            _collect_tasks(contexts, _finalize_special, jobs=1, step="finalize settings")
            _collect_tasks(contexts, _push_remote, jobs=jobs, step="push")
        return [context.report for context in contexts]


def sync_remote(
    config: AppConfig,
    remote: Remote,
    *,
    with_history: bool = False,
    dry_run: bool = False,
) -> SyncReport:
    return sync_remotes(
        config,
        [remote],
        with_history=with_history,
        dry_run=dry_run,
        jobs=1,
    )[0]
