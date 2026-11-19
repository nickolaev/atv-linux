import importlib.util
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('inject', HERE / 'inject.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Tests(unittest.TestCase):
    def test_actual_initrd_fit_and_key_mode(self):
        original = (mod.ROOT / 'image/recovery/mach_kernel').read_bytes()
        menu = (mod.ROOT / 'netbsd/macho/target/returning/menu-status.sh').read_bytes()
        poll = (HERE.parent / 'poll.sh').read_bytes()
        ident = b'\x7fELF\x01\x01\x01' + bytes(9)
        auth = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, 0, 52, 0, 0, 52, 32, 1, 0, 0, 0) + struct.pack('<8I', 1, 0, 0, 0, 0, 0, 5, 4096)
        output = mod.inject(original, menu, poll, auth, auth, bytes(32))
        off, size = mod.find_initrd(output)
        archive = mod.gzip.decompress(output[off:off+size])
        p = archive.index(b'atv-net-key\0') - 110
        self.assertEqual(int(archive[p+14:p+22], 16), 0o100600)
        p = archive.index(b'atv-supervise\0') - 110
        self.assertEqual(int(archive[p+14:p+22], 16), 0o100700)
        self.assertIn(b'[ ! -x /atv-supervise ]', archive)
        self.assertIn(b'3: Network agent', archive)
        self.assertIn(b'agent_pid=$!', archive)
        self.assertIn(b'/proc/$agent_pid/cmdline', archive)
        self.assertIn(b'/tmp/atv-netdiag-control', archive)
        self.assertIn(b'if [ -e "$control/busy" ]', archive)
        self.assertIn(b'stop_agent || continue', archive)
        self.assertIn(b'atvnet=off', archive)
        self.assertIn(b'Network setup failed; select 3 to retry.', archive)
        self.assertEqual(len(output), len(original))
        start = archive.index(b'# Per-image authenticated agent')
        end = archive.index(b'\nshow_status\n', start)
        self.functions = archive[start:end].decode().split("if ! grep -qw 'atvnet=off'", 1)[0]
        with tempfile.TemporaryDirectory() as work:
            control = Path(work) / 'control'
            control.mkdir()
            (control / 'busy').touch()
            code = self.functions.replace('/tmp/atv-netdiag-control', str(control))
            code += '\nagent_alive() { return 0; }; stop_agent; printf "result=%s\\n" "$?"\n'
            result = subprocess.run(['sh', '-c', code], text=True, capture_output=True, check=True)
            self.assertIn('result=1', result.stdout)
            self.assertFalse((control / 'stop').exists())
            self.assertFalse((control / 'lock').exists())

    def test_bad_inputs(self):
        with self.assertRaises(ValueError): mod.inject(b'bad', b'', b'', b'', b'', b'')

    def test_rejects_symlink_input_and_key_mode(self):
        with tempfile.TemporaryDirectory() as work:
            key = Path(work) / 'key'; key.write_bytes(bytes(32)); key.chmod(0o644)
            with self.assertRaises(ValueError): mod.read_regular(key, private=True)
            key.chmod(0o600)
            link = Path(work) / 'link'; link.symlink_to(key)
            with self.assertRaises(OSError): mod.read_regular(link, private=True)
