# ccsync

`ccsync` 通过 SSH/rsync 在本机与远程服务器之间双向同步 Codex 和 Claude Code 设置。它不需要中心服务器，也不会把配置或聊天上传到第三方。

主要特点：

- 模型、statusline、全局规则、agents、commands、hooks、skills 双向同步。
- 每台远端保留自己的 API key/token；远端没有密钥时才从本机初始化。
- 聊天历史默认关闭，需要时使用 `--with-history`。
- 覆盖前保留 rsync 备份，不同步删除操作。
- 不建立文件内容索引，只依据修改时间和文件大小工作。
- 日志只显示文件路径与同步方向，不打印配置内容。

## 要求

- 本机 Python 3.10+
- 本机和远端可通过 OpenSSH 连接
- 本机和远端已安装 rsync

建议先在 `~/.ssh/config` 中配置好主机别名并确认下面的命令可以连接：

```bash
ssh my-server
```

## 安装

推荐用 pipx 安装：

```bash
cd Claude-Codex-Settings
pipx install .
```

开发目录内也可以直接运行：

```bash
PYTHONPATH=src python3 -m ccsync.cli --help
```

## 快速开始

初始化配置：

```bash
ccsync init
```

添加使用 SSH alias 的服务器：

```bash
ccsync remote add gpu my-server
```

也可以显式指定用户、端口和私钥文件：

```bash
ccsync remote add gpu user@example.com --port 2222 --identity-file ~/.ssh/id_ed25519
```

先预览，再同步：

```bash
ccsync status gpu
ccsync sync gpu
```

同步所有服务器：

```bash
ccsync status --all
ccsync sync --all
```

包含全部持久化聊天记录：

```bash
ccsync status gpu --with-history
ccsync sync gpu --with-history
```

`status` 等价于只读预览。也可以运行 `ccsync sync gpu --dry-run`。

## 默认同步内容

Codex：

- `~/.codex/config.toml`
- `~/.codex/AGENTS.md`、`instructions.md`
- `~/.codex/rules/`、`skills/`
- `~/.codex/statusline*`

Claude Code：

- `~/.claude/settings.json`、`settings.local.json`
- `~/.claude.json`、`~/.claude/CLAUDE.md`
- `~/.claude/agents/`、`commands/`、`hooks/`、`skills/`
- 插件登记文件与 `~/.claude/statusline*`

开启 `--with-history` 后还包括：

- `~/.codex/sessions/`、`archived_sessions/`、`generated_images/`
- `~/.claude/projects/`、`history.jsonl`

缓存、日志、遥测、锁文件、shell snapshot、SQLite 及 WAL/SHM 文件不会同步。聊天历史适合备份和检索，但不同机器的项目绝对路径可能不同，因此不保证恢复一个正在运行的会话。

## 密钥规则

`~/.codex/auth.json` 和 `~/.claude/.credentials.json` 被视为整份认证文件：

- 远端已有文件时保持不变。
- 远端没有文件时从本机复制。
- 远端认证文件不会下载到本机。

在 JSON/TOML 设置中，名称包含 `api_key`、`apikey`、`token`、`secret`、`password` 或 `credential` 的字段也按机器保留。普通设置采用修改时间较新的版本；远端已有敏感字段优先，缺失字段才使用本机值。

这项规则不会同步系统环境变量、macOS Keychain、Linux secret service 或 SSH 私钥。需要同步其他独立认证文件时，将它加入下面的 `credential_paths`。

## 配置文件

默认位置为 `~/.config/ccsync/config.json`，权限为 `0600`：

```json
{
  "remotes": {
    "gpu": {
      "name": "gpu",
      "target": "my-server",
      "port": null,
      "identity_file": null
    }
  },
  "extra_paths": [
    ".config/my-statusline/"
  ],
  "credential_paths": [
    ".codex/auth.json",
    ".claude/.credentials.json"
  ]
}
```

路径必须相对于 HOME，不能使用 `..` 或 `~`。`extra_paths` 正常双向同步；`credential_paths` 只在远端缺失时初始化。如果 statusline 调用的是 HOME 之外的可执行文件，应在远端单独安装它，而不是把系统路径加入同步范围。

## 更新、冲突与备份

普通文件先执行远端到本机，再执行本机到远端，较新的修改时间获胜。两边时间一致且大小一致时视为未变化。工具不传播删除：一边删除的文件可能被另一边恢复。

被覆盖的文件保存在：

```text
~/.local/state/ccsync/backups/<远端名>/<UTC时间>/local/
~/.local/state/ccsync/backups/<远端名>/<UTC时间>/remote/
```

第二个路径位于远端服务器。恢复时，在确认目标文件没有被 Codex/Claude Code 使用后，从对应备份目录复制回来即可。备份不会自动删除。

为了减少运行中写入导致的不完整历史，建议在使用 `--with-history` 前退出两端正在运行的 Codex/Claude Code 会话。

## 开发验证

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m ccsync.cli --help
```
