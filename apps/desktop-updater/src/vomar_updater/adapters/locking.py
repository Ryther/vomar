"""Cross-process resource ownership without persisted operation approval."""
import os
from pathlib import Path

class FileLease:
    def __init__(self,path):self.path=Path(path);self.file=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.file=self.path.open('a+b');self.file.seek(0)
        if not self.file.read(1):self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:
            self.file.close();self.file=None;raise ValueError('Resource is already owned by another Vomar process') from e
        return self
    def close(self):
        if self.file:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            self.file.close();self.file=None
    def __enter__(self):return self.acquire()
    def __exit__(self,*_):self.close()
