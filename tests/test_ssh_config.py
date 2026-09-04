import tempfile
import unittest
from pathlib import Path

from ccsync.ssh_config import read_ssh_hosts


class SshConfigTest(unittest.TestCase):
    def test_reads_concrete_hosts_and_includes(self):
        with tempfile.TemporaryDirectory() as directory:
            ssh = Path(directory) / ".ssh"
            included = ssh / "conf.d"
            included.mkdir(parents=True)
            (ssh / "config").write_text(
                "Host gpu backup\n  HostName gpu.example.com\n"
                "Host *.internal !blocked\n"
                "Include conf.d/*\n",
                encoding="utf-8",
            )
            (included / "work").write_text("Host lab jump?\n", encoding="utf-8")

            self.assertEqual(read_ssh_hosts(ssh / "config"), ["gpu", "backup", "lab"])


if __name__ == "__main__":
    unittest.main()
