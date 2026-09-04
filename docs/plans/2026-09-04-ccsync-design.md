# ccsync 设计说明

## 目标

`ccsync` 是一个本地 Python CLI，通过 SSH/rsync 在本机和多台远程服务器之间同步 Codex 与 Claude Code 的配置。默认同步模型、statusline、规则、agents、commands、hooks 和 skills；聊天历史由 `--with-history` 显式开启。

## 同步模型

每台远程服务器独立同步。普通文件按修改时间双向更新：先拉取远端较新的文件，再把本机较新的文件推送到远端；修改时间相同时由远端版本优先。删除不传播。

工具不建立内容哈希数据库。每次覆盖发生前，rsync 把旧文件放入本地或远端的备份目录。同步期间不读取缓存、日志、遥测、锁文件和 SQLite/WAL 数据。

## 密钥规则

独立认证文件（如 `~/.codex/auth.json`）只在远端不存在时从本机初始化，之后不参与双向覆盖。对于 `settings.json` 和 `config.toml` 中的 `api_key`、`token`、`secret`、`password`、`credential` 字段，普通配置使用较新版本，但双方各自已有的敏感字段保留；远端缺少的敏感字段由本机补齐。远端密钥不会写回本机，也不会传播到其他远端。

## 范围

默认范围包括：

- Codex：`config.toml`、全局 AGENTS/指令、rules、skills 和常见 statusline 文件。
- Claude Code：`settings.json`、`settings.local.json`、`~/.claude.json`、CLAUDE.md、agents、commands、hooks、skills、插件登记文件和常见 statusline 文件。
- 用户在配置文件中声明的额外 HOME 相对路径。

`--with-history` 额外包含 Codex sessions、archived sessions、generated images，以及 Claude Code projects 和 `history.jsonl`。历史主要用于备份与检索，不承诺恢复跨机器正在运行的会话。

## 命令与安全

CLI 提供 `init`、`remote add/list`、`status` 和 `sync`。`status` 与 `sync --dry-run` 仅展示路径和方向，不输出文件内容。远端地址和额外路径均经过约束，密钥只通过 SSH 加密通道传输。项目仅依赖 Python 标准库及系统已有的 `ssh`、`rsync`。

## 验证

测试保持精简，只覆盖密钥合并、同步范围选择、配置读写和 SSH/rsync 参数生成。真实服务器连接由用户先运行 dry-run，再执行同步。
