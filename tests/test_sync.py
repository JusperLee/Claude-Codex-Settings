import unittest

from ccsync.config import Remote
from ccsync.sync import build_filters, rsync_command, ssh_command


class SyncCommandTest(unittest.TestCase):
    def test_commands_include_transport_and_safe_path_filters(self):
        remote = Remote("gpu", "alice@gpu.example", 2222, "/tmp/test key")

        self.assertEqual(
            ssh_command(remote, "mkdir -p ~/.codex"),
            ["ssh", "-p", "2222", "-i", "/tmp/test key", "alice@gpu.example", "mkdir -p ~/.codex"],
        )
        filters = build_filters([".claude/skills/", ".codex/AGENTS.md"])
        self.assertIn("--include=/.claude/skills/***", filters)
        self.assertIn("--include=/.codex/AGENTS.md", filters)
        command = rsync_command(remote, ["-a", "--ignore-existing"], "local", "alice@gpu.example:~/remote")
        self.assertIn("--ignore-existing", command)
        self.assertIn("ssh -p 2222 -i '/tmp/test key'", command)


if __name__ == "__main__":
    unittest.main()
