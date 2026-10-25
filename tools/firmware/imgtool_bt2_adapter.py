#!/usr/bin/env python3
"""Run unmodified SDK imgtool with one bounded encoder-only LZMA2 adjustment.

The raw ARMThumb/LZMA2 decoder format, dictionary and literal properties stay
unchanged. SDK imgtool still creates and signs every authenticated image/TLV.
"""
import lzma
from pathlib import Path
import runpy
import sys


def tuned_compress(original, data, *, format, filters, **kwargs):
    expected = [
        {'id': lzma.FILTER_ARMTHUMB},
        {'id': lzma.FILTER_LZMA2, 'preset': 9, 'dict_size': 32768, 'lp': 0, 'lc': 3},
    ]
    if format != lzma.FORMAT_RAW or filters != expected or kwargs:
        raise ValueError('bt2-48-32 requires exact SDK raw ARMThumb/LZMA2 32768/lc3/lp0/preset9 filters')
    selected = [dict(item) for item in filters]
    selected[1].update(mf=lzma.MF_BT2, nice_len=48, depth=32)
    return original(data, format=format, filters=selected)


def main():
    if len(sys.argv) < 3:
        raise SystemExit('usage: imgtool_bt2_adapter.py SDK_IMGTOOL arguments...')
    imgtool = Path(sys.argv[1]).resolve()
    arguments = sys.argv[2:]
    # The SDK writes pb into the stream properties separately; its compression
    # filter omits pb, whose liblzma default is 2. Require both to agree.
    if (arguments[0] != 'sign' or '--compression-lzma-pb' not in arguments or
            arguments[arguments.index('--compression-lzma-pb') + 1] != '2'):
        raise ValueError('bt2-48-32 requires sign with explicit pb=2')
    original = lzma.compress
    sys.path.insert(0, str(imgtool.parent))
    sys.argv = [str(imgtool), *arguments]
    lzma.compress = lambda data, **kwargs: tuned_compress(original, data, **kwargs)
    try:
        runpy.run_path(str(imgtool), run_name='__main__')
    finally:
        lzma.compress = original


if __name__ == '__main__':
    main()
