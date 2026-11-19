import ctypes,hashlib,hmac,subprocess,tempfile,pathlib
src=pathlib.Path('netbsd/macho/network_bootstrap/auth.c').resolve()
with tempfile.TemporaryDirectory() as t:
 so=pathlib.Path(t)/'auth.so'; subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Werror',str(src),'-o',str(so)],check=True)
 lib=ctypes.CDLL(str(so)); f=lib.atv_auth_verify; f.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p]
 key=bytes(range(32))
 for n in (0,1,55,56,63,64,100,1024):
  msg=bytes(i%251 for i in range(n)); tag=hmac.new(key,msg,hashlib.sha256).digest()
  assert f(key,msg,n,tag)==0; assert f(key,msg,n,bytes([tag[0]^1])+tag[1:])==-1
 assert f(key,b'x'*1025,1025,b'0'*32)==-1
 print('PASS: HMAC vectors, tampering, maximum bounds')
