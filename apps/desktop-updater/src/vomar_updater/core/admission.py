"""Process-local evidence seals prevent accidental construction/replacement of admitted data.

This is an API invariant, not a sandbox against arbitrary Python code execution.
"""
import hashlib,hmac,secrets,struct
_KEY=secrets.token_bytes(32)
def seal(label,*parts):
    raw=label.encode()+b'\0'
    for part in parts:
        b=part if isinstance(part,bytes) else str(part).encode();raw+=struct.pack('>Q',len(b))+b
    return hmac.digest(_KEY,raw,'sha256')
def require(actual,expected):
    if not isinstance(actual,bytes) or not hmac.compare_digest(actual,expected):raise ValueError('Object was not admitted by its authoritative validator or was modified')
