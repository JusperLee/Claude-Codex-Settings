from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
from pathlib import Path

from . import __version__
from .config import Remote, default_config_path, load_config, save_config
from .ssh_config import read_ssh_hosts
from .sync import SyncReport, sync_remotes


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


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
    add.add_argument("name", nargs="?")
    add.add_argument("target", nargs="?", help="SSH 目标，例如 user@example.com 或 SSH alias")
    add.add_argument(
        "--all",
        action="store_true",
        dest="all_from_ssh",
        help="导入 ~/.ssh/config 中的全部具体 Host",
    )
    add.add_argument("--port", type=int)
    add.add_argument("--identity-file")
    remote_commands.add_parser("list", help="列出远端")

    for name, help_text in (("status", "预览同步"), ("sync", "执行同步")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("remote", nargs="?", help="远端名称或带引号的通配模式")
        command.add_argument("--all", action="store_true", help="处理所有远端")
        command.add_argument("--with-history", action="store_true", help="包含全部聊天历史")
        command.add_argument("--jobs", type=_positive_int, default=4, help="并发远端数，默认 4")
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
        matched = [remote for remote_name, remote in config.remotes.items() if fnmatchcase(remote_name, name)]
        if not matched:
            raise SystemExit(f"未知远端：{name}")
        return matched
    if len(config.remotes) == 1:
        return list(config.remotes.values())
    raise SystemExit("请指定远端名称，或使用 --all")


def _print_summary(reports: list[SyncReport]) -> bool:
    succeeded = sum(report.ok for report in reports)
    failed = len(reports) - succeeded
    print(f"\n汇总：成功 {succeeded}，失败 {failed}")
    for report in reports:
        if report.ok:
            print(f"  OK  {report.remote}")
            continue
        print(f"  ERR {report.remote} ({len(report.failures)} 项)")
        for failure in report.failures:
            code = f"exit={failure.return_code}" if failure.return_code is not None else "internal"
            print(f"      {failure.step}: {code}, {failure.message}")
    return failed > 0


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
            if args.all_from_ssh:
                if args.name or args.target or args.port or args.identity_file:
                    raise SystemExit("remote add --all 不能与名称、目标、端口或身份文件同时使用")
                ssh_config = Path.home() / ".ssh" / "config"
                if not ssh_config.is_file():
                    raise SystemExit(f"SSH config 不存在：{ssh_config}")
                hosts = read_ssh_hosts(ssh_config)
                existing = sum(host in config.remotes for host in hosts)
                for host in hosts:
                    if host not in config.remotes:
                        config.remotes[host] = Remote(host, host)
                save_config(config, args.config)
                imported = len(hosts) - existing
                print(f"已从 {ssh_config} 导入 {imported} 个 Host，保留 {existing} 个同名远端")
                return
            if not args.name or not args.target:
                raise SystemExit("请提供 NAME TARGET，或使用 ccsync remote add --all")
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
    reports = sync_remotes(
        config,
        remotes,
        with_history=args.with_history,
        dry_run=dry_run,
        jobs=args.jobs,
    )
    if _print_summary(reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
