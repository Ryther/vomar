import io,struct,tracemalloc,zipfile,zlib
import pytest
from tools.firmware.bounded_zip import read_member


def test_false_zip_size_cannot_hide_unbounded_deflate_output():
    prefix=b'valid prefix';out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('payload',prefix+b'\0'*(8*1024*1024))
    raw=bytearray(out.getvalue());central=raw.index(b'PK\x01\x02');crc=zlib.crc32(prefix)
    struct.pack_into('<I',raw,14,crc);struct.pack_into('<I',raw,22,len(prefix));struct.pack_into('<I',raw,central+16,crc);struct.pack_into('<I',raw,central+24,len(prefix))
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        tracemalloc.start()
        try:
            with pytest.raises(ValueError):read_member(z,z.infolist()[0],1024)
            assert tracemalloc.get_traced_memory()[1]<2*1024*1024
        finally:tracemalloc.stop()

@pytest.mark.parametrize('method',[zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED])
def test_supported_archives_preserve_exact_member_bytes(method):
    raw=b'valid bounded component'*1024;out=io.BytesIO()
    with zipfile.ZipFile(out,'w',method) as z:z.writestr('payload',raw)
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as z:assert read_member(z,z.infolist()[0],len(raw))==raw
