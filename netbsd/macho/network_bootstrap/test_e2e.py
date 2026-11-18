"""Optional real BusyBox + i386 verifier + signed HTTP polling integration."""
import http.server
import os
import socket
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from controller import make_signed_handler, verify_report

ROOT = Path(__file__).resolve().parent


class SignedRoundTrip(unittest.TestCase):
    def test_real_agent_executes_authenticated_job_once(self):
        busybox = os.environ.get('ATV_BUSYBOX')
        auth = os.environ.get('ATV_AUTH')
        supervise = os.environ.get('ATV_SUPERVISE')
        if not busybox or not auth or not supervise:
            self.skipTest('set ATV_BUSYBOX, ATV_AUTH and ATV_SUPERVISE to tested Linux binaries')
        key = bytes(range(32))
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); (d/'key').write_bytes(key); (d/'key').chmod(0o600)
            (d/'entropy').write_text('256\n')
            marker = d/'runs'
            payload = f'printf "run\\n" >> "{marker}"\nprintf "network-roundtrip-ok\\n"\n'.encode()
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_signed_handler(payload, key, 1))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            for name in ('mktemp', 'chmod', 'mkdir', 'cat', 'hexdump', 'httpd', 'wget', 'sleep', 'setsid', 'kill', 'mv'):
                (d/name).symlink_to(busybox)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0)); report_port = probe.getsockname()[1]
            original = (ROOT/'poll.sh').read_text()
            self.assertIn('httpd -f -p 8081 ', original)
            control = d/'control'
            code = original.replace('/atv-auth', auth).replace('/atv-supervise', supervise).replace('/proc/sys/kernel/random/entropy_avail', str(d/'entropy')).replace('/tmp/atv-poll.XXXXXX', str(d/'poll.XXXXXX')).replace('/tmp/atv-netdiag-control', str(control)).replace('httpd -f -p 8081 ', f'httpd -f -p 127.0.0.1:{report_port} ')
            script = d/'poll.sh'; script.write_text(code)
            proc = subprocess.Popen([busybox, 'sh', str(script), f'http://127.0.0.1:{server.server_port}', str(d/'key')], env=dict(os.environ, PATH=str(d)+':'+os.environ['PATH']), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic()+30
                report = None
                while time.monotonic() < deadline:
                    files = list(d.glob('poll.*/export/report'))
                    if files:
                        report = files[0].read_bytes()
                        if b'exit=0' in report: break
                    if proc.poll() is not None: self.fail(f'agent exited: {proc.stderr.read()!r}')
                    time.sleep(.1)
                self.assertIsNotNone(report, 'no authenticated report arrived')
                session, seq, _ = report.split(b'\n', 1)[0].decode().split()
                body = verify_report(key, report, session, 1)
                self.assertIn(b'network-roundtrip-ok', body)
                self.assertIn(b'exit=0', body)
                with urllib.request.urlopen(f'http://127.0.0.1:{report_port}/report', timeout=3) as response:
                    self.assertEqual(response.read(), report)
                time.sleep(6)  # permit at least one more poll of the same job
                self.assertEqual(marker.read_text().splitlines(), ['run'])
                bad = bytearray(report); bad[-1] ^= 1
                with self.assertRaises(ValueError): verify_report(key, bytes(bad), session, 1)
                (control/'stop').touch()
                self.assertEqual(proc.wait(timeout=15), 0, 'agent did not stop cleanly')
                self.assertFalse(control.exists(), 'control lock leaked after stop')
                self.assertFalse([p for p in d.glob('poll.*') if p.is_dir()], 'private session files leaked after stop')
                with socket.socket() as check:
                    self.assertNotEqual(check.connect_ex(('127.0.0.1', report_port)), 0, 'listener survived stop')
                server2 = http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_signed_handler(b'echo second-controller\n', key, 2))
                thread2 = threading.Thread(target=server2.serve_forever, daemon=True); thread2.start()
                proc2 = subprocess.Popen([busybox, 'sh', str(script), f'http://127.0.0.1:{server2.server_port}', str(d/'key')], env=dict(os.environ, PATH=str(d)+':'+os.environ['PATH']), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic()+30
                    report2 = None
                    while time.monotonic()<deadline:
                        if proc2.poll() is not None: self.fail(f'restart exited: {proc2.stderr.read()!r}')
                        try:
                            with urllib.request.urlopen(f'http://127.0.0.1:{report_port}/report', timeout=1) as response:
                                candidate = response.read()
                            if b'second-controller' in candidate and b'exit=0' in candidate:
                                report2 = candidate; break
                        except urllib.error.HTTPError as error: error.close()
                        except (OSError, urllib.error.URLError): pass
                        time.sleep(.1)
                    self.assertIsNotNone(report2, 'second controller did not produce a complete report')
                    session2 = report2.split(b'\n', 1)[0].decode().split()[0]
                    self.assertNotEqual(session, session2)
                    self.assertIn(b'second-controller', verify_report(key, report2, session2, 2))
                    (control/'stop').touch()
                    self.assertEqual(proc2.wait(timeout=15), 0)
                    self.assertFalse([p for p in d.glob('poll.*') if p.is_dir()], 'reconfigured session files leaked after stop')
                finally:
                    if proc2.poll() is None:
                        try: os.killpg(proc2.pid, 9)
                        except ProcessLookupError: pass
                        proc2.wait(timeout=5)
                    proc2.stderr.close()
                    server2.shutdown(); server2.server_close(); thread2.join()
            finally:
                try: os.killpg(proc.pid, 9)
                except ProcessLookupError: pass
                proc.wait(timeout=5); proc.stderr.close()
                server.shutdown(); server.server_close(); thread.join()
                with socket.socket() as check:
                    self.assertNotEqual(check.connect_ex(('127.0.0.1', report_port)), 0, 'report listener leaked')


if __name__ == '__main__': unittest.main()
