#!/usr/bin/env python3
"""Capture one correlated NetBSD installer boot report on a diagnostic LAN."""
import argparse
from pathlib import Path
import re
import socket
import tempfile
import time


MAX_REPORT_BYTES = 65_536 + 32
REPORT_ENDINGS = (b"\nreport=complete\n", b"\nreport=truncated\n")


def receive_report(connection, launch_id, deadline):
    header = f"ATVNETBSD1 {launch_id}\n".encode("ascii")
    limit = len(header) + MAX_REPORT_BYTES
    data = bytearray()
    while len(data) <= limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("report deadline exceeded")
        connection.settimeout(remaining)
        chunk = connection.recv(min(4096, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if data[:len(header)] != header[:len(data)]:
            raise ValueError("unexpected report header")
    if len(data) > limit:
        raise ValueError("report exceeds byte limit")
    if not data.startswith(header) or not data.endswith(REPORT_ENDINGS):
        raise ValueError("incomplete report")
    return data


def save_report(output, data):
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.") as temporary:
        temporary.write(data)
        temporary.flush()
        # Publish the complete 0600 file in one operation, without replacing evidence.
        output.hardlink_to(temporary.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--source", required=True, help="expected sender IPv4 address")
    parser.add_argument("--launch-id", required=True)
    parser.add_argument("--timeout", type=int, default=180, help="overall time limit in seconds")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.launch_id) or args.timeout <= 0:
        parser.error("invalid launch ID or timeout")
    if args.output.exists():
        parser.error(f"report already exists at {args.output}")

    deadline = time.monotonic() + args.timeout
    try:
        with socket.create_server((args.bind, args.port)) as listener:
            print(f"Listening on {args.bind}:{args.port} for {args.launch_id}", flush=True)
            while (remaining := deadline - time.monotonic()) > 0:
                listener.settimeout(remaining)
                conn, (source, _) = listener.accept()
                with conn:
                    if source != args.source:
                        continue
                    try:
                        data = receive_report(conn, args.launch_id, min(deadline, time.monotonic() + 10))
                    except (OSError, ValueError) as error:
                        print(f"Discarded report from {source}: {error}", flush=True)
                        continue
                save_report(args.output, data)
                print(f"Saved {len(data)} bytes from {source} to {args.output}", flush=True)
                return
    except OSError as error:
        parser.exit(1, f"Unable to capture report: {error}\n")
    parser.exit(1, "Report deadline exceeded\n")


if __name__ == "__main__":
    main()
