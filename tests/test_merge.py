import unittest

from ccsync.merge import merge_json_values, merge_toml_text
from ccsync.profiles import sync_paths


class MergeTest(unittest.TestCase):
    def test_remote_keeps_its_key_and_missing_remote_key_uses_local(self):
        local = {"model": "local", "env": {"ANTHROPIC_API_KEY": "local-key"}}
        remote = {"model": "remote", "env": {"ANTHROPIC_API_KEY": "remote-key"}}

        local_result, remote_result = merge_json_values(local, remote, prefer_remote=True)
        self.assertEqual(local_result["env"]["ANTHROPIC_API_KEY"], "local-key")
        self.assertEqual(remote_result["env"]["ANTHROPIC_API_KEY"], "remote-key")
        self.assertEqual(local_result["model"], "remote")

        _, empty_remote_result = merge_json_values(local, {"model": "remote"}, prefer_remote=True)
        self.assertEqual(empty_remote_result["env"]["ANTHROPIC_API_KEY"], "local-key")

    def test_toml_merge_has_the_same_key_policy(self):
        local = 'model = "local"\n[mcp.env]\nAPI_TOKEN = "local-token"\n'
        remote = 'model = "remote"\n[mcp.env]\nAPI_TOKEN = "remote-token"\n'

        local_result, remote_result = merge_toml_text(local, remote, prefer_remote=True)

        self.assertIn('model = "remote"', local_result)
        self.assertIn('API_TOKEN = "local-token"', local_result)
        self.assertIn('API_TOKEN = "remote-token"', remote_result)

    def test_history_is_opt_in(self):
        default = sync_paths(False, [])
        history = sync_paths(True, [])

        self.assertNotIn(".claude/history.jsonl", default)
        self.assertIn(".claude/history.jsonl", history)
        self.assertIn(".codex/sessions/", history)


if __name__ == "__main__":
    unittest.main()
