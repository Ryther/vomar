"""Atomic, content-verified private backup archives."""
import os,zipfile
from pathlib import Path

def ensure_archive(destination,files):
 """Ensure ZIP has exactly the requested names and source bytes; repair partial ZIPs."""
 destination=Path(destination);expected={name:Path(path).read_bytes() for name,path in files.items()}
 def valid(path):
  try:
   with zipfile.ZipFile(path) as z:
    return len(z.namelist())==len(expected) and set(z.namelist())==set(expected) and z.testzip() is None and all(z.read(name)==data for name,data in expected.items())
  except (OSError,zipfile.BadZipFile,RuntimeError,EOFError):return False
 if valid(destination):return
 temporary=destination.with_suffix(destination.suffix+'.tmp')
 with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as z:
  for name,data in expected.items():z.writestr(name,data)
 if not valid(temporary):raise ValueError('Archive verification failed: '+str(temporary))
 with temporary.open('rb') as stream:os.fsync(stream.fileno())
 temporary.chmod(0o600);temporary.replace(destination)
