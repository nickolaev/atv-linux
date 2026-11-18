import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('private_build', HERE / 'private_build.py')
import sys
sys.path.insert(0, str(HERE))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        values = {}
        for name in ('original','menu','poll','auth','supervisor','key','shim','high','kernel','reference'):
            p = self.root / name; p.write_bytes(b'secret' if name == 'key' else name.encode()); p.chmod(0o600)
            values[name] = str(p)
        self.output = self.root / 'output'; values.update(output=str(self.output), recovery=str(self.root))
        self.args = SimpleNamespace(**values)

    def tearDown(self): self.temp.cleanup()

    def fake_module(self, name, path):
        if name == 'atv_returning_package': return SimpleNamespace(package=lambda *a: (b'combined', 1))
        def package(macho, kernel, ref, image, recovery, image_mib, recovery_mib, check):
            mask = os.umask(0o077); os.umask(mask)
            self.assertEqual(mask, 0o077)
            self.assertEqual(stat.S_IMODE(macho.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(macho.stat().st_mode), 0o600)
            image.write_bytes(b'private image')
        return SimpleNamespace(package=package)

    def test_private_output_and_cleanup(self):
        with patch.object(mod.inject, 'inject', return_value=b'prepared'), patch.object(mod, 'module', side_effect=self.fake_module):
            mod.build(self.args)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertEqual(self.output.read_bytes(), b'private image')
        self.assertEqual(Path(self.args.original).read_bytes(), b'original')
        self.assertFalse(list(self.root.glob('.atv-private-*')))

    def test_existing_output_and_symlink_preserved(self):
        self.output.write_bytes(b'keep')
        with self.assertRaises(ValueError): mod.build(self.args)
        self.assertEqual(self.output.read_bytes(), b'keep')
        self.output.unlink(); self.output.symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError): mod.build(self.args)
        self.assertTrue(self.output.is_symlink())

    def test_input_symlink_rejected_and_cleaned(self):
        p = Path(self.args.auth); p.unlink(); p.symlink_to(self.root / 'original')
        with self.assertRaises(OSError): mod.build(self.args)
        self.assertFalse(list(self.root.glob('.atv-private-*')))
        self.assertFalse(self.output.exists())

    def test_builder_failure_does_not_publish(self):
        def fail(*args): raise ValueError('failed')
        with patch.object(mod.inject, 'inject', return_value=b'prepared'), patch.object(mod, 'module', side_effect=lambda *a: SimpleNamespace(package=fail)):
            with self.assertRaises(ValueError): mod.build(self.args)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.atv-private-*')))

    def test_rejects_shared_writable_parent(self):
        shared = self.root / 'shared'; shared.mkdir(); shared.chmod(0o777)
        self.args.output = str(shared / 'output')
        with self.assertRaises(ValueError): mod.build(self.args)
        self.assertFalse((shared / 'output').exists())

    def test_publish_race_preserves_new_file(self):
        def target(macho, kernel, ref, image, recovery, image_mib, recovery_mib, check):
            image.write_bytes(b'private image')
            self.output.write_bytes(b'created during build')
        def fake(name, path):
            if name == 'atv_returning_package': return SimpleNamespace(package=lambda *a: (b'combined', 1))
            return SimpleNamespace(package=target)
        with patch.object(mod.inject, 'inject', return_value=b'prepared'), patch.object(mod, 'module', side_effect=fake):
            with self.assertRaises(FileExistsError): mod.build(self.args)
        self.assertEqual(self.output.read_bytes(), b'created during build')
        self.assertFalse(list(self.root.glob('.atv-private-*')))
