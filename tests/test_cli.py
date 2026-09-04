import unittest

from ccsync.cli import _selected_remotes
from ccsync.config import AppConfig, Remote


class CliTest(unittest.TestCase):
    def test_remote_name_accepts_glob_pattern(self):
        config = AppConfig(
            remotes={
                "img18": Remote("img18", "img18"),
                "img72": Remote("img72", "img72"),
                "cpu": Remote("cpu", "cpu"),
            }
        )

        selected = _selected_remotes(config, "img*", False)

        self.assertEqual([remote.name for remote in selected], ["img18", "img72"])


if __name__ == "__main__":
    unittest.main()
