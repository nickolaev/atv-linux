"""Host checks for the exact-kernel checkpoint hash gate."""
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class HashTests(unittest.TestCase):
    def test_sha256_vectors_and_wrong_kernel_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            stub = tmp / 'stub.c'
            stub.write_text('int checkpoint_enter(unsigned a,unsigned b,unsigned c,unsigned d){return -1;}\nvoid checkpoint_return(void){}\n')
            output = tmp / 'hash.so'
            subprocess.run([os.environ.get('CC', 'cc'), '-shared', '-fPIC',
                            '-DTARGET_NATIVE_CHECKPOINT', '-DCHECKPOINT_TEST_HASH',
                            str(HERE / 'checkpoint.c'), str(stub), '-o', str(output)], check=True)
            lib = ctypes.CDLL(str(output))
            lib.checkpoint_test_sha256.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            lib.checkpoint_run.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                           ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p,
                                           ctypes.c_uint32]
            for data in (b'', b'abc', b'a' * 55, b'b' * 56, b'c' * 64, b'd' * 10000):
                src = ctypes.create_string_buffer(data)
                digest = (ctypes.c_ubyte * 32)()
                lib.checkpoint_test_sha256(src, len(data), digest)
                self.assertEqual(bytes(digest), hashlib.sha256(data).digest())
            wrong = ctypes.create_string_buffer(b'not the pinned kernel')
            self.assertEqual(lib.checkpoint_run(wrong, len(wrong.raw), 0x5000000, 0x3008000, 1, None, 0), -1)


if __name__ == '__main__':
    unittest.main()
