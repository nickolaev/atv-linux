import hashlib
import hmac
import os
import contextlib
import http.server
import io
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from controller import make_signed_handler, read_key, signed_manifest, verify_report


class SignedControllerTests(unittest.TestCase):
    def test_session_discovery_is_unverified_and_deduplicated(self):
        key, session = bytes(range(32)), 'ab' * 16
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_signed_handler(b'echo ok\n', key, 1))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                for _ in range(2):
                    with urlopen(f'http://127.0.0.1:{server.server_port}/manifest/{session}') as response:
                        self.assertEqual(response.read(), signed_manifest(key, session, 1, b'echo ok\n'))
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(output.getvalue().count(session), 1)
        self.assertIn('unverified until a signed report is checked', output.getvalue())

    def test_authenticated_report_and_replay(self):
        key, session, sequence = bytes(range(32)), 'ab' * 16, 42
        body = b'job output\nexit=0\n'
        seq = f'{sequence:016x}'
        tag = hmac.new(key, b'ATV1-REPORT\0' + session.encode() + seq.encode() + body,
                       hashlib.sha256).hexdigest().encode()
        report = session.encode() + b' ' + seq.encode() + b' ' + tag + b'\n' + body
        self.assertEqual(verify_report(key, report, session, sequence), body)
        for altered, requested_session, requested_seq in [
            (report[:-1] + b'X', session, sequence),
            (report, 'cd' * 16, sequence),
            (report, session, sequence + 1),
            (report[:90], session, sequence),
            (report[:50] + b'X' + report[51:], session, sequence),
        ]:
            with self.assertRaises(ValueError):
                verify_report(key, altered, requested_session, requested_seq)

    def test_wire_format_and_tamper(self):
        key = bytes(range(32))
        data = b'echo hello\n'
        manifest = signed_manifest(key, '12' * 16, 1, data)
        self.assertEqual(len(manifest), 200)
        self.assertEqual(manifest[70:134], hashlib.sha256(data).hexdigest().encode())
        self.assertEqual(manifest[135:199], hmac.new(key, manifest[:134], hashlib.sha256).hexdigest().encode())
        self.assertNotEqual(manifest[135:199], hmac.new(key, b'X' + manifest[1:134], hashlib.sha256).hexdigest().encode())
        for session, seq in [('x' * 32, 1), ('a' * 32, 0), ('a' * 32, 1 << 64)]:
            with self.assertRaises(ValueError):
                signed_manifest(key, session, seq, data)

    def test_key_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'key'
            p.write_bytes(bytes(32)); p.chmod(0o600)
            self.assertEqual(read_key(p), bytes(32))
            p.chmod(0o644)
            with self.assertRaises(ValueError): read_key(p)
            p.unlink(); p.symlink_to('/dev/null')
            with self.assertRaises(OSError): read_key(p)


if __name__ == '__main__': unittest.main()
