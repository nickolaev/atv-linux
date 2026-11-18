import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("run.sh")

class MaintenanceTest(unittest.TestCase):
    def test_configures_ssh_idempotently(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            mock = base / "bin"
            mock.mkdir()
            assets = base / "assets"
            assets.mkdir()
            (assets / "authorized_keys").write_text("ssh-ed25519 AAAATEST test\n")
            (assets / "provision.sh").write_text("#!/bin/sh\nexit 0\n")
            root = base / "root"
            (root / "etc/ssh").mkdir(parents=True)
            (root / "root").mkdir()
            (root / "etc/rc.conf").write_text("hostname=atv\n")
            (root / "etc/ssh/sshd_config").write_text("PermitRootLogin no\n# defaults\n")
            (base / "dev").mkdir()
            (base / "dev/MAKEDEV").write_text("#!/bin/sh\nexit 0\n")
            checker = base / "check-target"
            checker.write_text("#!/bin/sh\nexit 0\n")
            checker.chmod(0o755)
            for name, body in {
                "dkctl": "echo 'dk3: atv-root, 10 blocks at 0, type: ffs'",
                "mount": "exit 0",
                "umount": "exit 0",
                "chown": "exit 0",
                "nc": "cat > /dev/null",
                "sync": "exit 0",
            }.items():
                p = mock / name
                p.write_text("#!/bin/sh\n" + body + "\n")
                p.chmod(0o755)
            script = SCRIPT.read_text()
            script = script.replace("PATH=/sbin:/bin:/usr/sbin:/usr/bin", f"PATH={mock}:/usr/bin:/bin")
            script = script.replace("assets=/usr/atv-maintenance", f"assets={assets}")
            script = script.replace("state=/var/db/atv-maintenance", f"state={base}/state")
            script = script.replace("log=/var/log/atv-maintenance.log", f"log={base}/log")
            script = script.replace("root=/mnt/atv-installed", f"root={root}")
            script = script.replace("/usr/atv-installer/bin/check-target.sh", str(checker))
            script = script.replace("cd /dev &&", f"cd {base}/dev &&")
            run = base / "run.sh"
            run.write_text(script)
            for _ in range(2):
                subprocess.run(["sh", str(run)], check=True)
            self.assertEqual((root / "root/.ssh/authorized_keys").read_text(), "ssh-ed25519 AAAATEST test\n")
            self.assertEqual((root / "etc/rc.conf").read_text().count("sshd=YES"), 1)
            config = (root / "etc/ssh/sshd_config").read_text()
            self.assertEqual(config.count("PermitRootLogin"), 1)
            self.assertTrue(config.startswith("PermitRootLogin prohibit-password\n"))
            self.assertEqual((root / "etc/rc.local").read_text().count("/usr/local/sbin/atv-provision-packages"), 1)
            self.assertTrue((root / "usr/local/sbin/atv-provision-packages").exists())
            self.assertIn("result=ssh-configured", (base / "state/report.txt").read_text())

if __name__ == "__main__":
    unittest.main()
