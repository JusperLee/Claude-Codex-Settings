import unittest
from unittest.mock import patch

from ccsync.config import AppConfig, Remote
from ccsync.sync import build_filters, rsync_command, ssh_command, sync_remotes


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

    def test_batch_collects_failure_without_stopping_other_remotes(self):
        remotes = [Remote("bad", "bad-host"), Remote("good", "good-host")]
        visited = []

        def status(context):
            visited.append(context.remote.name)
            if context.remote.name == "bad":
                raise RuntimeError("unavailable")

        with patch("ccsync.sync._status_remote", side_effect=status):
            reports = sync_remotes(AppConfig(), remotes, dry_run=True, jobs=2)

        by_name = {report.remote: report for report in reports}
        self.assertCountEqual(visited, ["bad", "good"])
        self.assertFalse(by_name["bad"].ok)
        self.assertTrue(by_name["good"].ok)


if __name__ == "__main__":
    unittest.main()
