from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .config import Remote, default_config_path, load_config, save_config
from .sync import sync_remote


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccsync",
        description="通过 SSH 双向同步 Codex 与 Claude Code 设置",
    )
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="创建本地配置")

    remote = commands.add_parser("remote", help="管理远端")
    remote_commands = remote.add_subparsers(dest="remote_command", required=True)
    add = remote_commands.add_parser("add", help="添加或更新远端")
    add.add_argument("name")
    add.add_argument("target", help="SSH 目标，例如 user@example.com 或 SSH alias")
    add.add_argument("--port", type=int)
    add.add_argument("--identity-file")
    remote_commands.add_parser("list", help="列出远端")

    for name, help_text in (("status", "预览同步"), ("sync", "执行同步")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("remote", nargs="?")
        command.add_argument("--all", action="store_true", help="处理所有远端")
        command.add_argument("--with-history", action="store_true", help="包含全部聊天历史")
        if name == "sync":
            command.add_argument("--dry-run", action="store_true", help="仅预览")
    return parser


def _selected_remotes(config, name: str | None, all_remotes: bool) -> list[Remote]:
    if name and all_remotes:
        raise SystemExit("不能同时指定远端名称和 --all")
    if all_remotes:
        if not config.remotes:
            raise SystemExit("尚未配置远端；请先运行 ccsync remote add")
        return list(config.remotes.values())
    if name:
        if name not in config.remotes:
            raise SystemExit(f"未知远端：{name}")
        return [config.remotes[name]]
    if len(config.remotes) == 1:
        return list(config.remotes.values())
    raise SystemExit("请指定远端名称，或使用 --all")


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    config = load_config(args.config)

    if args.command == "init":
        if args.config.exists():
            print(f"配置已存在：{args.config}")
        else:
            save_config(config, args.config)
            print(f"已创建配置：{args.config}")
        return

    if args.command == "remote":
        if args.remote_command == "add":
            identity = str(Path(args.identity_file).expanduser()) if args.identity_file else None
            remote = Remote(args.name, args.target, args.port, identity)
            config.remotes[remote.name] = remote
            save_config(config, args.config)
            print(f"已保存远端：{remote.name} ({remote.target})")
        else:
            for remote in config.remotes.values():
                details = [remote.target]
                if remote.port:
                    details.append(f"port={remote.port}")
                if remote.identity_file:
                    details.append(f"identity={remote.identity_file}")
                print(f"{remote.name}: {' '.join(details)}")
        return

    remotes = _selected_remotes(config, args.remote, args.all)
    dry_run = args.command == "status" or args.dry_run
    for remote in remotes:
        sync_remote(config, remote, with_history=args.with_history, dry_run=dry_run)


if __name__ == "__main__":
    main()
