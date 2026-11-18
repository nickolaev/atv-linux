import hashlib
import os
import subprocess
import tempfile
import unittest
import threading
import time
import http.server
import io
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT = Path(__file__).with_name('bootstrap.sh')
from controller import bounded_report, make_handler


class BootstrapTests(unittest.TestCase):
    def test_output_cap_leaves_room_for_signed_report_footer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'entropy').write_text('256\n')
            supervisor = root / 'supervise'
            supervisor.write_text('#!/bin/sh\ndd if=/dev/zero bs=1048576 count=10 2>/dev/null\n')
            supervisor.chmod(0o755)
            code = Path(__file__).with_name('poll.sh').read_text().replace('#!/bin/sh\n', '', 1)
            code = code.replace('/tmp/atv-netdiag-control', tmp + '/control').replace('/tmp/atv-poll.XXXXXX', tmp + '/poll.XXXXXX').replace('/proc/sys/kernel/random/entropy_avail', tmp + '/entropy').replace('/atv-auth', 'mock_auth').replace('/atv-supervise', str(supervisor))
            mocks = '''httpd() { exec sleep 60; }
mv() { command mv "$@" && cp "$3" "$TEST_CAPTURE"; }
hexdump() { printf 00000000000000000000000000000000; }
mock_auth() { if [ "$1" = sign-report ]; then printf '%064d\\n' 0; else echo 0000000000000001; fi; }
sleep() { if [ "$1" = 1 ]; then :; else exit 0; fi; }
wget() { while [ "$#" -gt 0 ]; do if [ "$1" = -O ]; then dest=$2; shift 2; continue; fi; url=$1; shift; done
 case "$url" in */manifest/*) echo 'ATV1 00000000000000000000000000000000 0000000000000001 shell 00000001 digest mac' > "$dest" ;; */payload/*) echo ok > "$dest" ;; *) return 1 ;; esac; }
'''
            run = subprocess.run(['sh', '-c', mocks + code, 'test', 'http://host', 'key'], env=dict(os.environ, TEST_CAPTURE=tmp+'/capture'), capture_output=True, timeout=8)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = (root / 'capture').read_bytes()
            self.assertLess(len(report), 8 * 1024 * 1024)
            self.assertIn(b'may be truncated', report[-200:])
            self.assertIn(b'job=0000000000000001 exit=', report[-200:])

    def test_agent_refuses_failed_http_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'entropy').write_text('256\n')
            ctl = root / 'control'
            code = Path(__file__).with_name('poll.sh').read_text().replace('#!/bin/sh\n', '', 1)
            code = code.replace('/tmp/atv-netdiag-control', str(ctl)).replace('/tmp/atv-poll.XXXXXX', tmp + '/poll.XXXXXX').replace('/proc/sys/kernel/random/entropy_avail', str(root / 'entropy'))
            mocks = 'httpd() { return 1; }; hexdump() { printf 00000000000000000000000000000000; }; wget() { echo SHOULD_NOT_POLL; };\n'
            result = subprocess.run(['sh', '-c', mocks + code, 'test', 'http://host', 'key'], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('report server failed to start', result.stderr)
            self.assertNotIn('SHOULD_NOT_POLL', result.stdout)
            self.assertFalse(ctl.exists())

    def test_cooperative_stop_refuses_busy_and_exits_when_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'entropy').write_text('256\n')
            (root / 'supervise').write_text('#!/bin/sh\nshift\nexec sh "$@"\n'); (root / 'supervise').chmod(0o755)
            ctl = root / 'control'
            code = Path(__file__).with_name('poll.sh').read_text().replace('#!/bin/sh\n', '', 1)
            code = code.replace('/tmp/atv-netdiag-control', str(ctl)).replace('/tmp/atv-poll.XXXXXX', tmp + '/poll.XXXXXX').replace('/proc/sys/kernel/random/entropy_avail', str(root / 'entropy')).replace('/atv-auth', 'mock_auth').replace('/atv-supervise', str(root / 'supervise')).replace('    sleep 5\n', '    sleep 1\n')
            mocks = '''httpd() { exec sleep 60; }
hexdump() { printf 00000000000000000000000000000000; }
mock_auth() { if [ "$1" = sign-report ]; then printf '%064d\\n' 0; else echo 0000000000000001; fi; }
wget() {
 while [ "$#" -gt 0 ]; do if [ "$1" = -O ]; then dest=$2; shift 2; continue; fi; url=$1; shift; done
 case "$url" in */manifest/*) echo 'ATV1 00000000000000000000000000000000 0000000000000001 shell 00000001 digest mac' > "$dest" ;;
 */payload/*) echo 'sleep 2' > "$dest" ;; *) return 1 ;; esac
}
'''
            shell = [os.environ['ATV_BUSYBOX'], 'sh'] if os.environ.get('ATV_BUSYBOX') else ['sh']
            proc = subprocess.Popen(shell + ['-c', mocks + code, 'test', 'http://host', 'key'], env=dict(os.environ, PATH=tmp+':'+os.environ['PATH']), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not (ctl / 'busy').exists() and time.monotonic() < deadline: time.sleep(.02)
                self.assertTrue((ctl / 'busy').exists())
                while True:
                    try: (ctl / 'lock').mkdir(); break
                    except FileExistsError:
                        if time.monotonic() >= deadline: raise
                        time.sleep(.01)
                self.assertTrue((ctl / 'busy').exists()); (ctl / 'lock').rmdir()
                while (ctl / 'busy').exists() and time.monotonic() < deadline: time.sleep(.02)
                self.assertFalse((ctl / 'busy').exists())
                while True:
                    try: (ctl / 'lock').mkdir(); break
                    except FileExistsError:
                        if time.monotonic() >= deadline: raise
                        time.sleep(.01)
                (ctl / 'stop').touch(); (ctl / 'lock').rmdir()
                self.assertEqual(proc.wait(timeout=5), 0)
                self.assertFalse(ctl.exists())
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()

    def test_poller_rejects_unready_entropy_before_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            entropy = Path(tmp) / 'entropy'; entropy.write_text('0\n')
            code = Path(__file__).with_name('poll.sh').read_text().replace('/tmp/atv-poll.XXXXXX', tmp + '/poll.XXXXXX').replace('/proc/sys/kernel/random/entropy_avail', str(entropy)).replace('#!/bin/sh\n', '', 1)
            mocks = 'sleep() { :; }; httpd() { echo SHOULD_NOT_START; };\n'
            run = subprocess.run(['sh', '-c', mocks + code, 'test', 'http://host', 'key'], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('entropy pool not ready', run.stderr)
            self.assertNotIn('SHOULD_NOT_START', run.stdout)

    def test_repeated_start_failure_cleans_owned_work_and_keeps_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); entropy = root / 'entropy'; entropy.write_text('0\n')
            key = root / 'key'; key.write_bytes(b'keep-key')
            code = Path(__file__).with_name('poll.sh').read_text().replace('#!/bin/sh\n', '', 1)
            code = code.replace('/tmp/atv-netdiag-control', tmp + '/control').replace('/tmp/atv-poll.XXXXXX', tmp + '/poll.XXXXXX').replace('/proc/sys/kernel/random/entropy_avail', str(entropy))
            shell = [os.environ['ATV_BUSYBOX'], 'sh'] if os.environ.get('ATV_BUSYBOX') else ['sh']
            for _ in range(2):
                result = subprocess.run(shell + ['-c', 'sleep() { :; };\n' + code, 'test', 'http://host', str(key)], capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(key.read_bytes(), b'keep-key')
                self.assertFalse(list(root.glob('poll.*')))
                self.assertFalse((root / 'control').exists())

    def test_report_truncation_is_explicit(self):
        self.assertEqual(bounded_report(io.BytesIO(b'12345'), 4), (b'1234', True))
        self.assertEqual(bounded_report(io.BytesIO(b'1234'), 4), (b'1234', False))

    def test_explicit_job_ids_allow_reruns(self):
        first = make_handler(b'echo ok\n', 'secret', 'run1')
        second = make_handler(b'echo ok\n', 'secret', 'run2')
        self.assertIsNot(first, second)
        with self.assertRaises(ValueError):
            make_handler(b'echo ok\n', 'secret', '../bad')

    def test_controller_requires_token_and_serves_manifest(self):
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_handler(b'echo ok\n', 'secret'))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/manifest'
            with self.assertRaises(urllib.error.HTTPError) as failure:
                urllib.request.urlopen(url)
            self.assertEqual(failure.exception.code, 403)
            failure.exception.close()
            request = urllib.request.Request(url, headers={'Authorization': 'Bearer secret'})
            with urllib.request.urlopen(request) as response:
                job, digest = response.read().decode().split()
            self.assertEqual(digest, hashlib.sha256(b'echo ok\n').hexdigest())
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/payload/{job}', headers={'Authorization': 'Bearer secret'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.read(), b'echo ok\n')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_poller_executes_verified_job_once(self):
        payload = b'printf "polled job\\n"\n'
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'payload'
            src.write_bytes(payload)
            supervise = Path(tmp) / 'supervise'; supervise.write_text('#!/bin/sh\nshift\nexec sh "$@"\n'); supervise.chmod(0o755)
            code = Path(__file__).with_name('poll.sh').read_text().replace('/tmp/atv-poll.XXXXXX', tmp + '/poll.XXXXXX')
            (Path(tmp) / 'entropy').write_text('256\n')
            code = code.replace('#!/bin/sh\n', '', 1).replace('/atv-auth', 'mock_auth').replace('/atv-supervise', str(supervise)).replace('/proc/sys/kernel/random/entropy_avail', tmp + '/entropy')
            mocks = '''httpd() { exec sleep 60; }
mv() { command mv "$@" && cp "$3" "$TEST_CAPTURE"; }
hexdump() { printf 00000000000000000000000000000000; }
mock_auth() { if [ "$1" = sign-report ]; then printf '%064d\\n' 0; else printf '0000000000000001\\n'; fi; }
sleep() { if [ "$1" = 120 ]; then command sleep 10; elif [ "$1" = 1 ]; then :; else exit 0; fi; }
timeout() { shift 2; "$@"; }
wget() {
  while [ "$#" -gt 0 ]; do
    if [ "$1" = -O ]; then dest=$2; shift 2; continue; fi
    url=$1; shift
  done
  case "$url" in */manifest/*) printf 'ATV1 00000000000000000000000000000000 0000000000000001 shell 00000001 %s mac\\n' "$TEST_DIGEST" > "$dest" ;;
    */payload/0000000000000001) cp "$PAYLOAD_SOURCE" "$dest" ;;
    *) return 1 ;; esac
}
'''
            env = dict(os.environ, PATH=tmp+':'+os.environ['PATH'], PAYLOAD_SOURCE=str(src), TEST_DIGEST=hashlib.sha256(payload).hexdigest(), TEST_CAPTURE=tmp+'/capture')
            run = subprocess.run(['sh', '-c', mocks + code, 'test', 'http://host', 'token'],
                                 capture_output=True, text=True, env=env, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = Path(tmp) / 'capture'
            self.assertIn('polled job', report.read_text())
            self.assertIn('job=0000000000000001 exit=0', report.read_text())

    def test_poller_retries_download_then_does_not_rerun(self):
        payload = b'printf "executed\\n" >> "$TEST_RUNS"\n'
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'payload'; src.write_bytes(payload)
            supervise = Path(tmp) / 'supervise'; supervise.write_text('#!/bin/sh\nshift\nexec sh "$@"\n'); supervise.chmod(0o755)
            (Path(tmp) / 'entropy').write_text('256\n')
            code = Path(__file__).with_name('poll.sh').read_text().replace('/tmp/atv-poll.XXXXXX', tmp + '/poll.XXXXXX').replace('#!/bin/sh\n', '', 1).replace('/atv-auth', 'mock_auth').replace('/atv-supervise', str(supervise)).replace('/proc/sys/kernel/random/entropy_avail', tmp + '/entropy')
            mocks = '''httpd() { exec sleep 60; }
hexdump() { printf 00000000000000000000000000000000; }
mock_auth() { if [ "$1" = sign-report ]; then printf '%064d\\n' 0; else printf '0000000000000001\\n'; fi; }
timeout() { shift 2; "$@"; }
sleep() { if [ "$1" = 1 ]; then :; elif [ "$1" = 120 ]; then command sleep 10; else n=$(( ${n:-0} + 1 )); [ "$n" -lt 3 ] || exit 0; fi; }
wget() {
 while [ "$#" -gt 0 ]; do if [ "$1" = -O ]; then dest=$2; shift 2; continue; fi; url=$1; shift; done
 case "$url" in */manifest/*) printf 'ATV1 00000000000000000000000000000000 0000000000000001 shell 00000001 %s mac\\n' "$TEST_DIGEST" > "$dest" ;;
 */payload/0000000000000001) if [ ! -f "$TEST_ATTEMPT" ]; then : > "$TEST_ATTEMPT"; return 1; fi; cp "$PAYLOAD_SOURCE" "$dest" ;;
 *) return 1 ;; esac
}
'''
            env = dict(os.environ, PATH=tmp+':'+os.environ['PATH'], PAYLOAD_SOURCE=str(src), TEST_DIGEST=hashlib.sha256(payload).hexdigest(), TEST_ATTEMPT=tmp+'/attempt', TEST_RUNS=tmp+'/runs')
            run = subprocess.run(['sh', '-c', mocks + code, 'test', 'http://host', 'token'], capture_output=True, text=True, env=env, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(Path(tmp+'/runs').read_text().splitlines(), ['executed'])

    def test_verified_payload_requires_explicit_confirmation(self):
        payload = b'printf "ran diagnostic\\n"\n'
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'source'
            src.write_bytes(payload)
            code = SCRIPT.read_text().replace('/tmp/atv-netdiag.XXXXXX', tmp + '/diag.XXXXXX')
            code = ('ifconfig() { :; }; udhcpc() { :; }; httpd() { :; }; '
                    'wget() { cp "$PAYLOAD_SOURCE" "$3"; };\n' + code + '\nnetwork_bootstrap\n')
            env = dict(os.environ, PAYLOAD_SOURCE=str(src))
            args = 'http://host/diag\n' + digest + '\n'
            denied = subprocess.run(['sh', '-c', code], input=args + 'no\n', text=True, capture_output=True, env=env)
            self.assertNotEqual(denied.returncode, 0)
            self.assertNotIn('ran diagnostic', denied.stdout)
            accepted = subprocess.run(['sh', '-c', code], input=args + 'yes\n', text=True, capture_output=True, env=env)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn('ran diagnostic', accepted.stdout)
            self.assertIn(':8081/status.txt', accepted.stdout)

    def test_rejects_non_http_before_download(self):
        stub = 'ifconfig() { :; }; udhcpc() { :; }; wget() { echo BAD; }\n'
        cmd = stub + '. "$1"; network_bootstrap'
        result = subprocess.run(['sh', '-c', cmd, 'test', str(SCRIPT)], input='file:///etc/passwd\n', text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('BAD', result.stdout)

    def test_rejects_invalid_digest(self):
        stub = 'ifconfig() { :; }; udhcpc() { :; }; wget() { echo BAD; }\n'
        cmd = stub + '. "$1"; network_bootstrap'
        result = subprocess.run(['sh', '-c', cmd, 'test', str(SCRIPT)], input='http://example/diag\nxyz\n', text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('BAD', result.stdout)


if __name__ == '__main__':
    unittest.main()
