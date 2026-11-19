#!/usr/bin/env python3
"""Serve one trusted shell diagnostic and retrieve the resulting report."""
import argparse
import hashlib
import hmac
import http.server
import os
import stat
import sys
from pathlib import Path
from urllib.request import urlopen


def read_key(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('key must be a mode-0600 regular file')
        key = os.read(fd, 33)
        if len(key) != 32:
            raise ValueError('key must contain exactly 32 bytes')
        return key
    finally:
        os.close(fd)


def signed_manifest(key, session, sequence, payload):
    if len(key) != 32 or len(session) != 32 or any(c not in '0123456789abcdef' for c in session):
        raise ValueError('invalid key or session')
    if not 0 < sequence < 1 << 64 or not 0 < len(payload) <= 32 * 1024 * 1024:
        raise ValueError('invalid sequence or payload size')
    header = f'ATV1 {session} {sequence:016x} shell {len(payload):08x} {hashlib.sha256(payload).hexdigest()}'.encode('ascii')
    return header + b' ' + hmac.new(key, header, hashlib.sha256).hexdigest().encode('ascii') + b'\n'


def make_signed_handler(payload, key, sequence):
    observed_sessions = set()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if self.path.startswith('/manifest/'):
                    session = self.path[len('/manifest/'):]
                    body = signed_manifest(key, session, sequence, payload)
                    if session not in observed_sessions:
                        if len(observed_sessions) >= 64:
                            observed_sessions.clear()
                        observed_sessions.add(session)
                        print(f'Observed session {session} (unverified until a signed report is checked)',
                              flush=True)
                elif self.path == f'/payload/{sequence:016x}':
                    body = payload
                else:
                    self.send_error(404); return
            except ValueError:
                self.send_error(400); return
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, format, *args):
            pass
    return Handler


def bounded_report(response, limit=16 * 1024 * 1024):
    data = response.read(limit + 1)
    return data[:limit], len(data) > limit


def verify_report(key, report, session, sequence):
    """Authenticate a bounded report for one job/session.

    This stateless check cannot distinguish replay of an older valid report
    from the same job, such as a running snapshot after its final snapshot.
    """
    if (len(key) != 32 or len(session) != 32 or
            any(c not in '0123456789abcdef' for c in session) or
            not 0 < sequence < 1 << 64):
        raise ValueError('invalid key, session or sequence')
    if len(report) < 115 or len(report) > 16 * 1024 * 1024:
        raise ValueError('invalid report size')
    prefix = f'{session} {sequence:016x} '.encode('ascii')
    if not report.startswith(prefix) or report[114:115] != b'\n':
        raise ValueError('stale or malformed report header')
    tag, body = report[50:114], report[115:]
    expected = hmac.new(key, b'ATV1-REPORT\0' + session.encode('ascii') +
                        f'{sequence:016x}'.encode('ascii') + body, hashlib.sha256).hexdigest().encode('ascii')
    if not hmac.compare_digest(tag, expected):
        raise ValueError('invalid report authentication')
    return body


def make_handler(payload, token, job_id=None):
    digest = hashlib.sha256(payload).hexdigest()
    # A changed payload creates a new job; a reboot may run it again.
    job = job_id or digest[:24]
    if not job or not all(c.isascii() and (c.isalnum() or c in '_-') for c in job):
        raise ValueError('job ID must use ASCII letters, digits, underscore or hyphen')

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            actual = self.headers.get('Authorization', '')
            if not hmac.compare_digest(actual, 'Bearer ' + token):
                self.send_error(403)
                return
            if self.path == '/manifest':
                body = f'{job} {digest}\n'.encode('ascii')
            elif self.path == '/payload/' + job:
                body = payload
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('payload', type=Path)
    serve.add_argument('--token', required=True)
    serve.add_argument('--bind', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8082)
    serve.add_argument('--job-id', help='new ID to rerun identical payload')
    signed = sub.add_parser('serve-signed')
    signed.add_argument('payload', type=Path)
    signed.add_argument('--key-file', type=Path, required=True)
    signed.add_argument('--sequence', type=int, required=True)
    signed.add_argument('--bind', default='127.0.0.1')
    signed.add_argument('--port', type=int, default=8082)
    fetch = sub.add_parser('fetch')
    fetch.add_argument('host', help='Apple TV IP address')
    verified = sub.add_parser('fetch-signed')
    verified.add_argument('host', help='Apple TV IP address')
    verified.add_argument('--key-file', type=Path, required=True)
    verified.add_argument('--session', required=True)
    verified.add_argument('--sequence', type=int, required=True)
    args = p.parse_args()
    if args.command == 'fetch-signed':
        try:
            key = read_key(args.key_file)
            with urlopen(f'http://{args.host}:8081/report', timeout=10) as response:
                data, truncated = bounded_report(response)
            if truncated:
                raise ValueError('report exceeds 16 MiB')
            body = verify_report(key, data, args.session, args.sequence)
        except (OSError, ValueError) as error:
            p.error(str(error))
        sys.stdout.buffer.write(body)
        return
    if args.command == 'fetch':
        with urlopen(f'http://{args.host}:8081/status.txt', timeout=10) as response:
            data, truncated = bounded_report(response)
            if truncated:
                print('Report exceeds 16 MiB; output truncated and footer may be missing.', file=sys.stderr)
            print(data.decode('utf-8', 'replace'), end='')
        return
    if args.command == 'serve-signed':
        data = args.payload.read_bytes()
        try:
            key = read_key(args.key_file)
            signed_manifest(key, '0' * 32, args.sequence, data)
        except (OSError, ValueError) as error:
            p.error(str(error))
        server = http.server.ThreadingHTTPServer((args.bind, args.port), make_signed_handler(data, key, args.sequence))
        print(f'Serving signed sequence {args.sequence} on {args.bind}:{args.port}', flush=True)
        server.serve_forever()
        return
    if not args.token or not all(c.isascii() and (c.isalnum() or c in '_-') for c in args.token):
        p.error('token must use ASCII letters, digits, underscore or hyphen')
    data = args.payload.read_bytes()
    if not data or len(data) > 32 * 1024 * 1024:
        p.error('payload must be between 1 byte and 32 MiB')
    try:
        handler = make_handler(data, args.token, args.job_id)
    except ValueError as error:
        p.error(str(error))
    server = http.server.ThreadingHTTPServer((args.bind, args.port), handler)
    print(f'Serving {hashlib.sha256(data).hexdigest()} on {args.bind}:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
