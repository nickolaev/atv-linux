import hashlib
import hmac
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent

class AuthCliTest(unittest.TestCase):
    def test_static_i386_manifest_and_replay(self):
        if platform.system() != 'Linux' or not shutil.which('clang') or not shutil.which('ld.lld'):
            self.skipTest('requires Linux, clang and lld with i386 execution')
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d); binary = d/'verifier'
            subprocess.run(['clang','--target=i386-unknown-linux-gnu','-march=pentium-m','-mno-sse','-mno-sse2','-mno-mmx','-mno-80387','-ffreestanding','-fno-stack-protector','-fno-pic','-fno-pie','-fno-builtin','-Os','-nostdlib','-no-pie','-fuse-ld=lld','-Wl,-static,-e,_start,--build-id=none,--no-dynamic-linker',str(ROOT/'auth_cli.c'),str(ROOT/'auth.c'),'-o',str(binary)],check=True)
            key=bytes(range(32)); payload=b'test payload'; session='01'*16; last='0'*16
            (d/'key').write_bytes(key); (d/'key').chmod(0o600); (d/'payload').write_bytes(payload)
            body=f'ATV1 {session} 0000000000000001 shell {len(payload):08x} {hashlib.sha256(payload).hexdigest()}'.encode()
            valid=body+b' '+hmac.new(key,body,hashlib.sha256).hexdigest().encode()+b'\n'
            (d/'manifest').write_bytes(valid)
            def run(nonce=session,seq=last):
                return subprocess.run([str(binary),str(d/'key'),str(d/'manifest'),str(d/'payload'),nonce,seq],capture_output=True)
            self.assertEqual(run().returncode,0)
            self.assertNotEqual(run(seq='0000000000000001').returncode,0)
            self.assertNotEqual(run(nonce='02'*16).returncode,0)
            for offset in (5,38,55,61,70,135,199):
                changed=bytearray(valid);changed[offset]^=1;(d/'manifest').write_bytes(changed)
                self.assertNotEqual(run().returncode,0,offset)
            (d/'manifest').write_bytes(valid);(d/'payload').write_bytes(b'other payload')
            self.assertNotEqual(run().returncode,0)
            (d/'payload').write_bytes(payload);(d/'key').chmod(0o644)
            self.assertNotEqual(run().returncode,0)
            (d/'key').chmod(0o600)
            for report in (b'',b'hello\x00world',bytes(range(256))*40):
                (d/'report').write_bytes(report)
                signed=subprocess.run([str(binary),'sign-report',str(d/'key'),session,'0000000000000001',str(d/'report')],capture_output=True)
                self.assertEqual(signed.returncode,0)
                self.assertEqual(signed.stdout,hmac.new(key,b'ATV1-REPORT\0'+session.encode()+b'0000000000000001'+report,hashlib.sha256).hexdigest().encode()+b'\n')
                altered=hmac.new(key,b'ATV1-REPORT\0'+session.encode()+b'0000000000000001'+report+b'!',hashlib.sha256).hexdigest().encode()+b'\n'
                self.assertNotEqual(signed.stdout,altered)
                for nonce,seq in (('02'*16,'0000000000000001'),(session,'0000000000000002')):
                    wrong=hmac.new(key,b'ATV1-REPORT\0'+nonce.encode()+seq.encode()+report,hashlib.sha256).hexdigest().encode()+b'\n'
                    self.assertNotEqual(signed.stdout,wrong)
            (d/'report').write_bytes(b'x'*(8*1024*1024+1))
            self.assertNotEqual(subprocess.run([str(binary),'sign-report',str(d/'key'),session,'0000000000000001',str(d/'report')],capture_output=True).returncode,0)
            for length in (4095,4096,4097,8192,8193,131079):
                payload=bytes(i%251 for i in range(length));(d/'payload').write_bytes(payload)
                body=f'ATV1 {session} 0000000000000001 shell {length:08x} {hashlib.sha256(payload).hexdigest()}'.encode()
                (d/'manifest').write_bytes(body+b' '+hmac.new(key,body,hashlib.sha256).hexdigest().encode()+b'\n')
                self.assertEqual(run().returncode,0,length)
                (d/'payload').write_bytes(payload+b'x');self.assertNotEqual(run().returncode,0,length)
                (d/'payload').write_bytes(payload[:-1]);self.assertNotEqual(run().returncode,0,length)

if __name__=='__main__': unittest.main()
