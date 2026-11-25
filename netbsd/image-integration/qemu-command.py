#!/usr/bin/env python3
"""Run a command at the root console of a disposable NetBSD EFI VM.

The boot image and data disk must both be disposable writable files. Console
output remains on the VM display; the command should export its own results.
"""
import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("disk", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("command")
    parser.add_argument("--wait", type=int, default=100)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--disk-model", default="QEMU HARDDISK")
    parser.add_argument("--assets-iso", type=Path)
    parser.add_argument("--assets-fat", type=Path)
    parser.add_argument("--memory", default="256M")
    parser.add_argument("--debug-reset", action="store_true")
    args = parser.parse_args()
    if args.image.resolve() == args.disk.resolve():
        parser.error("image and disposable target disk must differ")
    args.work.mkdir()
    firmware = Path("/opt/homebrew/share/qemu")
    variables = args.work / "vars.fd"
    shutil.copyfile(firmware / "edk2-i386-vars.fd", variables)
    qmp = args.work / "qmp.sock"
    command = [
        "/opt/homebrew/bin/qemu-system-i386", "-machine", "pc,accel=tcg",
        "-cpu", "pentium3", "-m", args.memory,
        "-drive", f"if=pflash,format=raw,readonly=on,file={firmware / 'edk2-i386-code.fd'}",
        "-drive", f"if=pflash,format=raw,file={variables}",
        "-drive", f"if=none,id=usb,format=raw,file={args.image}",
        "-device", "qemu-xhci,id=xhci", "-device", "usb-storage,drive=usb,bootindex=1",
        "-drive", f"if=none,id=target,format=raw,file={args.disk}",
        "-device", f"ide-hd,drive=target,model={args.disk_model}",
        "-vga", "std", "-display", "none", "-monitor", "none",
        "-serial", f"file:{args.work / 'serial.log'}",
        "-netdev", "user,id=net0,net=192.168.100.0/24,dhcpstart=192.168.100.191",
        "-device", "rtl8139,netdev=net0",
        "-qmp", f"unix:{qmp},server=on,wait=off", "-no-reboot", "-no-shutdown",
    ]
    if args.assets_iso:
        command.extend(["-drive", f"if=ide,media=cdrom,format=raw,readonly=on,file={args.assets_iso}"])
    if args.assets_fat:
        command.extend(["-drive", f"if=none,id=assets,format=raw,readonly=on,file={args.assets_fat}",
                        "-device", "usb-storage,drive=assets,bus=xhci.0"])
    if args.debug_reset:
        command.extend(["-d", "int,cpu_reset", "-D", str(args.work / "qemu-debug.log")])
    vm = subprocess.Popen(command)
    try:
        for _ in range(100):
            if qmp.exists():
                break
            time.sleep(0.1)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(10)
            sock.connect(str(qmp))
            with sock.makefile("rb") as replies:
                replies.readline()

                def send(execute, arguments=None):
                    request = {"execute": execute}
                    if arguments:
                        request["arguments"] = arguments
                    sock.sendall(json.dumps(request).encode() + b"\n")
                    while True:
                        response = json.loads(replies.readline())
                        if "event" in response:
                            with (args.work / "events.log").open("a") as log:
                                log.write(json.dumps(response) + "\n")
                        if "error" in response:
                            raise RuntimeError(response["error"])
                        if "return" in response:
                            return response["return"]

                send("qmp_capabilities")
                time.sleep(args.wait)
                mapping = {" ": "spc", "/": "slash", ".": "dot", "-": "minus",
                           ":": "shift-semicolon", ";": "semicolon", "_": "shift-minus",
                           "=": "equal", "\n": "ret"}
                for char in "root\n" + args.command + "\n":
                    if char in mapping:
                        key = mapping[char]
                    elif char.isascii() and char.islower() or char.isdigit():
                        key = char
                    else:
                        raise ValueError(f"unsupported console character {char!r}")
                    send("human-monitor-command", {"command-line": "sendkey " + key})
                    time.sleep(0.08)
                deadline = time.monotonic() + args.duration
                while time.monotonic() < deadline:
                    (args.work / "status.json").write_text(json.dumps(send("query-status")))
                    send("screendump", {"filename": str(args.work / "screen.ppm")})
                    extra = args.work / "keys"
                    if extra.exists():
                        for key in extra.read_text().splitlines():
                            send("human-monitor-command", {"command-line": "sendkey " + key})
                        extra.unlink()
                    if (args.work / "stop").exists():
                        break
                    time.sleep(min(10, max(0, deadline - time.monotonic())))
    finally:
        vm.terminate()
        vm.wait(timeout=10)


if __name__ == "__main__":
    main()
