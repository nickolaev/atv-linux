"""Integration checks for a separately built Linux/i386 supervisor."""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


@unittest.skipUnless(os.environ.get('ATV_SUPERVISOR'), 'set ATV_SUPERVISOR to the Linux/i386 binary')
class SupervisorTests(unittest.TestCase):
    def run_job(self, text, seconds=2):
        with tempfile.TemporaryDirectory() as d:
            job = Path(d) / 'job.sh'
            job.write_text(text)
            return subprocess.run([os.environ['ATV_SUPERVISOR'], str(seconds), str(job)],
                                  capture_output=True, text=True, timeout=8)

    def test_exit_and_output(self):
        result = self.run_job('echo hello; exit 7\n')
        self.assertEqual((result.returncode, result.stdout), (7, 'hello\n'))

    def test_timeout_and_child(self):
        result = self.run_job('trap "" TERM; sleep 20 & echo $!; wait\n', 1)
        self.assertEqual(result.returncode, 124)
        pid = int(result.stdout.strip())
        for _ in range(30):
            stat = Path('/proc') / str(pid) / 'stat'
            if not stat.exists() or stat.read_text().split(') ', 1)[1][0] == 'Z':
                break
            time.sleep(.1)
        else:
            self.fail('child is still running after supervisor return')

    def test_bad_arguments(self):
        result = subprocess.run([os.environ['ATV_SUPERVISOR'], '0', '/nope'])
        self.assertEqual(result.returncode, 125)

    @unittest.skipUnless(os.environ.get('ATV_SUPERVISOR_DELAY'), 'set ATV_SUPERVISOR_DELAY to test delayed setsid')
    def test_delayed_setsid_does_not_hang(self):
        started = time.monotonic()
        result = subprocess.run([os.environ['ATV_SUPERVISOR_DELAY'], '1', '/nope'],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 124)
        self.assertLess(time.monotonic() - started, 4)


if __name__ == '__main__':
    unittest.main()
