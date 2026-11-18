#!/usr/bin/env python3
"""Capture one correlated Multiboot entry checkpoint on a diagnostic LAN."""
import argparse
from ipaddress import IPv4Address
import os
from pathlib import Path
import re
import socket
import time


def receive_checkpoint(listener, source, launch_id, deadline):
    header = f"ATVMB1 {launch_id} ".encode("ascii")
    expected = re.compile(re.escape(header) + rb"EAX=[0-9a-f]{8} EBX=[0-9a-f]{8}\n")
    while (remaining := deadline - time.monotonic()) > 0:
        listener.settimeout(remaining)
        packet, (sender, _) = listener.recvfrom(512)
        if sender == source and expected.fullmatch(packet):
            return packet
    raise TimeoutError("checkpoint deadline exceeded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", type=IPv4Address, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8084)
    parser.add_argument("--source", type=IPv4Address, required=True)
    parser.add_argument("--launch-id", required=True)
    parser.add_argument("--timeout", type=int, default=180, help="overall time limit in seconds")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.launch_id):
        parser.error("invalid launch ID")
    if not 1 <= args.port <= 65535 or args.timeout <= 0:
        parser.error("invalid port or timeout")
    if args.output.exists():
        parser.error(f"checkpoint already exists at {args.output}")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
            listener.bind((str(args.bind), args.port))
            print(f"Listening on {args.bind}:{args.port} for {args.launch_id}", flush=True)
            deadline = time.monotonic() + args.timeout
            packet = receive_checkpoint(listener, str(args.source), args.launch_id, deadline)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(packet)
    except OSError as error:
        parser.exit(1, f"Unable to capture checkpoint: {error}\n")
    print(f"Saved {len(packet)} bytes from {args.source} to {args.output}", flush=True)


if __name__ == "__main__":
    main()
