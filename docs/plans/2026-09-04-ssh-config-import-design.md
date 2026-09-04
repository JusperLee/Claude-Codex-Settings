# SSH config 批量导入设计

`ccsync remote add --all` 读取本机 `~/.ssh/config`，将具体的 `Host` 别名批量加入 ccsync。导入后的远端以别名本身作为 SSH target，因此 HostName、User、Port、IdentityFile、ProxyJump 等连接细节继续由 OpenSSH 处理，ccsync 不复制这些字段，也不向远端发送 SSH config 或私钥。

解析器处理一个 `Host` 行中的多个别名，并按原位置读取 `Include` 指向的文件。包含 `*`、`?`、`!` 或字符范围的 Host 模式不会导入。已有同名 ccsync 远端保持原配置，防止批量导入覆盖用户显式设置。重复别名只记录一次；不存在的 Include 文件直接忽略。主配置文件不存在时，命令明确退出。

实现分为两个小步骤：首先增加独立 SSH config 解析器和一个覆盖多别名、通配项及 Include 的测试；然后将 `--all` 接入 `remote add`，更新帮助与 README，并运行现有精简测试套件和 CLI 演练。
