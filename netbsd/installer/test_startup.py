import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.mock("sleep", "exit 0")
        self.env = {**os.environ}

    def mock(self, name, code):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + code + "\n")
        path.chmod(0o755)

    def script(self, name):
        text = (HERE / name).read_text().replace(
            "PATH=/sbin:/bin:/usr/sbin:/usr/bin",
            f"PATH={self.bin}:/bin:/usr/bin",
        )
        text = text.replace("/usr/atv-installer", str(self.root / "assets"))
        text = text.replace("/var/db/atv-installer", str(self.root / "state"))
        text = text.replace("/var/log/atv-install.log", str(self.root / "log"))
        text = text.replace("/var/run/atv-ready-report.txt", str(self.root / "ready"))
        path = self.root / name
        path.write_text(text)
        return path

    def test_interrupted_install_reports_without_reinstall(self):
        state = self.root / "state"
        state.mkdir()
        (state / "install-started").write_text("started")
        subprocess.run(["sh", self.script("startup.sh")], check=True, env=self.env)
        report = (state / "install-report.txt").read_text()
        self.assertIn("result=interrupted", report)
        self.assertIn("report=complete", report)

    def test_ready_requires_root_swap_network_and_hostname(self):
        self.mock("hostname", "echo atv")
        self.mock("ifconfig", "echo 'inet 192.168.100.191'")
        self.mock("dkctl", "printf 'dk4: atv-root, 1 blocks\\ndk5: atv-swap, 1 blocks\\n'")
        self.mock("mount", "echo '/dev/dk4 on / type ffs (local)'")
        self.mock("swapctl", "echo '/dev/dk5 1048576 0'")
        script = self.script("ready.sh")
        subprocess.run(["sh", script], check=True, env=self.env)
        self.assertIn("result=ready", (self.root / "ready").read_text())
        self.mock("swapctl", "echo 'no swap devices configured'")
        subprocess.run(["sh", script], check=True, env=self.env)
        self.assertIn("result=degraded", (self.root / "ready").read_text())
        self.mock("swapctl", "echo '/dev/dk5 1048576 0'")
        self.mock("mount", "echo '/dev/dk4 on / type msdos (local)'")
        subprocess.run(["sh", script], check=True, env=self.env)
        self.assertIn("result=degraded", (self.root / "ready").read_text())


if __name__ == "__main__":
    unittest.main()
