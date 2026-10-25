"""Resource-bounded ZIP member reads shared by runtime and reference validators.

CPython ZipExtFile truncates output to a declared uncompressed size before CRC
checking. A counting decompressor rejects dishonest output lengths before that
truncation, and bounded read requests avoid allocating an entire hostile stream.
The updater pins CPython3.13; unsupported internal codec behavior fails closed.
"""
import zipfile

class CountingDeflate:
    def __init__(self,decoder,limit):self.decoder=decoder;self.limit=limit;self.used=0
    def decompress(self,data,max_length=0):
        allowance=self.limit-self.used+1
        result=self.decoder.decompress(data,min(max_length,allowance) if max_length>0 else allowance)
        self.used+=len(result)
        if self.used>self.limit:raise ValueError('ZIP output exceeds its declared member bound')
        return result
    def __getattr__(self,name):return getattr(self.decoder,name)


def read_member(archive,info,limit):
    if info.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) or info.file_size<0 or info.file_size>limit:raise ValueError('Unsupported or oversized ZIP member')
    if info.compress_type==zipfile.ZIP_STORED and info.compress_size!=info.file_size:raise ValueError('Stored ZIP size mismatch')
    with archive.open(info) as stream:
        if info.compress_type==zipfile.ZIP_DEFLATED:
            decoder=getattr(stream,'_decompressor',None)
            if decoder is None or not hasattr(decoder,'eof'):raise ValueError('Unsupported bounded ZIP codec')
            stream._decompressor=CountingDeflate(decoder,info.file_size)
        result=stream.read(info.file_size+1)
        if len(result)!=info.file_size:raise ValueError('ZIP member length mismatch')
        if info.compress_type==zipfile.ZIP_DEFLATED and (not stream._decompressor.eof or stream._decompressor.unused_data or stream._compress_left):raise ValueError('Trailing or incomplete compressed ZIP stream')
        return result
