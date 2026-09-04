import stat
import tempfile
import unittest
from pathlib import Path

from ccsync.config import AppConfig, Remote, load_config, save_config


class ConfigTest(unittest.TestCase):
    def test_round_trip_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = AppConfig(
                remotes={"gpu": Remote("gpu", "alice@gpu.example", 2222, "/tmp/id")},
                extra_paths=[".config/my-statusline"],
            )

            save_config(config, path)

            self.assertEqual(load_config(path), config)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
