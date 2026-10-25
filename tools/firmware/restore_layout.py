#!/usr/bin/env python3
"""Host-only stock-restore coverage/fault model; never accesses hardware.

Models page erase/program separately, not NVMC word timing or reboot code.
"""
import argparse
import hashlib
import json
from pathlib import Path

PAGE = 0x1000
SIZE = 0x100000
BOOT_END = 0xc000
SCRATCH_START = 0xb0000
SCRATCH_END = 0xef000
ERASED = bytes([255]) * PAGE


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate(reference):
    if len(reference) != SIZE:
        raise ValueError('reference must cover exactly 1 MiB')
    if reference[SCRATCH_START:SCRATCH_END] != bytes([255]) * (SCRATCH_END-SCRATCH_START):
        raise ValueError('stock scratch interval is not entirely erased')


def operations(reference):
    """All writes outside boot/scratch precede irreversible boot replacement."""
    validate(reference)
    for phase, addresses in (
        ('stream', range(BOOT_END, SIZE, PAGE)),
        ('boot', range(0, BOOT_END, PAGE)),
        ('cleanup', range(SCRATCH_START, SCRATCH_END, PAGE)),
    ):
        # The SRAM finalizer erases the whole boot region before programming
        # any boot words. Keep that interruption window in the page model.
        if phase == 'boot':
            for address in addresses:
                yield phase, address, 'erase', ERASED
        for address in addresses:
            if phase == 'stream' and SCRATCH_START <= address < SCRATCH_END:
                continue
            if phase != 'boot':
                yield phase, address, 'erase', ERASED
            # Erased pages require erase, but no program operation.
            data = reference[address:address+PAGE]
            if data != ERASED:
                yield phase, address, 'program', data


def simulate(reference):
    validate(reference)
    # Deliberately make every starting page differ, including erased target pages.
    flash = bytearray(x ^ 0x5a for x in reference)
    custom_boot = bytes(flash[:BOOT_END])
    protected = bytes(flash[SCRATCH_START:SCRATCH_END])
    counts = dict(stream=0, boot=0, cleanup=0)
    checkpoints = dict(custom_boot_intact=0, boot_transition=0,
                       stock_boot_complete_cleanup_pending=0, exact=0)
    touched = set()
    for phase, address, kind, data in operations(reference):
        flash[address:address+PAGE] = data
        touched.add(address)
        counts[phase] += 1
        if phase == 'stream':
            assert bytes(flash[:BOOT_END]) == custom_boot
            assert bytes(flash[SCRATCH_START:SCRATCH_END]) == protected
            checkpoints['custom_boot_intact'] += 1
            # Replaying this page after a cut produces the exact expected page.
            replay = bytearray(flash)
            replay[address:address+PAGE] = ERASED
            replay[address:address+PAGE] = reference[address:address+PAGE]
            assert replay[address:address+PAGE] == reference[address:address+PAGE]
        elif bytes(flash[:BOOT_END]) != reference[:BOOT_END]:
            checkpoints['boot_transition'] += 1
        elif flash != reference:
            checkpoints['stock_boot_complete_cleanup_pending'] += 1
        else:
            checkpoints['exact'] += 1
    assert flash == reference
    assert touched == set(range(0, SIZE, PAGE))
    return dict(sha256=sha(reference), size=len(reference), pages=len(touched),
                scratch_bytes=SCRATCH_END-SCRATCH_START,
                operation_counts=counts, interruption_checkpoints=checkpoints,
                final_byte_identical=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    args = parser.parse_args()
    result = dict(actual_reference=simulate(args.reference.read_bytes()))
    # Artificial DK reference: not a bootable image and never programmed.
    synthetic = bytearray((i * 17 + (i >> 12)) & 255 for i in range(SIZE))
    synthetic[SCRATCH_START:SCRATCH_END] = bytes([255])*(SCRATCH_END-SCRATCH_START)
    result['artificial_dk_reference'] = simulate(bytes(synthetic))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
