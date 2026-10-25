"""Native immutable publication: POSIX links/fsync, Windows write-through move."""
import ctypes
import errno
import os
from pathlib import Path


def publish_new(source,destination):
    source=Path(source);destination=Path(destination)
    if source.parent!=destination.parent:raise ValueError('Publication must stay on the same directory/volume')
    if os.name=='nt':
        from ctypes import wintypes
        move=ctypes.WinDLL('kernel32',use_last_error=True).MoveFileExW
        move.argtypes=(wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD);move.restype=wintypes.BOOL
        # WRITE_THROUGH, deliberately without REPLACE_EXISTING/COPY_ALLOWED.
        if not move(str(source),str(destination),0x8):
            error=ctypes.get_last_error()
            if error in (80,183):raise FileExistsError(errno.EEXIST,'Destination already exists',str(destination))
            raise ctypes.WinError(error)
    else:os.link(source,destination)


def sync_directory(path):
    # Windows namespace publication uses MoveFileExW WRITE_THROUGH; file content
    # is flushed before the move. POSIX requires syncing the containing directory.
    if os.name!='nt':
        fd=os.open(path,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)


def ensure_directory(path):
    path=Path(path)
    if not path.exists():
        ensure_directory(path.parent)
        try:path.mkdir(mode=0o700)
        except FileExistsError:pass
    if not path.is_dir():raise ValueError('Private evidence directory is invalid')
    sync_directory(path)
    if path.parent!=path:sync_directory(path.parent)
