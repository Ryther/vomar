"""Derive a pinned compact SDK while keeping interception boundaries native."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

try:
    from .prepare_diag_batch_sdk import (
        ARCHIVE_SHA, different_source, prepare_archive as prepare_trace,
        verify_member, verify_diagnostics_member,
    )
except ImportError:
    from prepare_diag_batch_sdk import (
        ARCHIVE_SHA, different_source, prepare_archive as prepare_trace,
        verify_member, verify_diagnostics_member,
    )

KIND = 'compact-native-boundaries-v1'
PRODUCTION_SHA = '335b864955b53d42d364ba018391db03afba4fd061e96190d7c36daab101a5fa'
NATIVE_SHA = {
    'nwk_main.o': 'c8b1ddc761663a73ee66b931dab07e66747d37bf3261c909b2aefaf847f0b722',
    'zb_scheduler.o': '238c18734c94fa3128d6855c938848456b4ef774438150e049d0c88a3f41a6e5',
}
TRANSFORMED_SHA = {
    'zb_bufpool_mult.o': '02e8db57b02afa11fb566aa80b3faa7c720eed28ad123a7e612a302a8f09c5d8',
    'zdo_diagnostics.o': '5e9993271a165c5c876467a54ea4e1c8378bd65c6182d555223763e10e79b392',
}
TRACE_MEMBERS = ('zb_bufpool_mult.o', 'zb_bufpool_mult_storage.o', 'zdo_diagnostics.o')
BOUNDARIES = (*NATIVE_SHA, *TRACE_MEMBERS)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_members(ar, archive):
    archive = Path(archive).resolve()
    names = subprocess.check_output([str(ar), 't', str(archive)], text=True, timeout=30).splitlines()
    if (not names or len(names) != len(set(names)) or
            any(Path(name).name != name or not name.endswith('.o') for name in names)):
        raise ValueError('Unique flat SDK object members required')
    return {name: subprocess.check_output([str(ar), 'p', str(archive), name], timeout=30)
            for name in names}


def verify_report(report, ar):
    if not isinstance(report, dict) or any(
            not isinstance(report.get(name), str) or not report[name]
            for name in ('source', 'trace_source', 'archive')):
        raise ValueError('Invalid compact SDK report paths')
    source, trace, output = (Path(report[name]).resolve() for name in ('source', 'trace_source', 'archive'))
    if (report.get('kind') != KIND or report.get('source_sha256') != PRODUCTION_SHA or
            sha(source.read_bytes()) != PRODUCTION_SHA):
        raise ValueError('Unreviewed production SDK')
    if report.get('trace_source_sha256') != ARCHIVE_SHA or sha(trace.read_bytes()) != ARCHIVE_SHA:
        raise ValueError('Unreviewed trace SDK')
    if sha(output.read_bytes()) != report.get('archive_sha256'):
        raise ValueError('Compact archive hash mismatch')
    production, original_trace, actual = (read_members(ar, path) for path in (source, trace, output))
    if set(actual) != set(production):
        raise ValueError('Compact member set changed')
    for name, raw in actual.items():
        if name in TRANSFORMED_SHA and sha(raw) != TRANSFORMED_SHA[name]:
            raise ValueError('Unreviewed transformed trace member: ' + name)
        if name in NATIVE_SHA:
            if sha(raw) != NATIVE_SHA[name]:
                raise ValueError('Unreviewed compiled native member: ' + name)
        elif name == 'zb_bufpool_mult.o':
            verify_member(original_trace[name], raw)
        elif name == 'zdo_diagnostics.o':
            verify_diagnostics_member(original_trace[name], raw)
        elif raw != (original_trace[name] if name in TRACE_MEMBERS else production[name]):
            raise ValueError('Unexpected SDK member modification: ' + name)
    return True


def prepare_archive(source, trace_source, output, ar, objcopy, cc):
    source, trace_source, output = map(lambda p: Path(p).resolve(), (source, trace_source, output))
    if sha(source.read_bytes()) != PRODUCTION_SHA:
        raise ValueError('Pinned production SDK required')
    if sha(trace_source.read_bytes()) != ARCHIVE_SHA:
        raise ValueError('Pinned trace SDK required')
    different_source(source, output)
    different_source(trace_source, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    commands = []
    with tempfile.TemporaryDirectory(prefix='compact-sdk-', dir=output.parent) as temporary:
        folder = Path(temporary)
        derived_trace = folder / 'trace.a'
        trace_proof = prepare_trace(trace_source, derived_trace, ar, objcopy)
        production, trace = (read_members(ar, path) for path in (source, derived_trace))
        files = []
        for name in BOUNDARIES:
            dest = folder / name
            if name in NATIVE_SHA:
                original = folder / ('production-lto-' + name)
                original.write_bytes(production[name])
                command = [str(cc), '-mcpu=cortex-m4', '-mthumb', '-mabi=aapcs',
                           '-mfloat-abi=hard', '-mfpu=fpv4-sp-d16', '-Oz', '-fno-inline',
                           '-ffunction-sections', '-fdata-sections', '-flto', '-r',
                           '-nostdlib', '-flinker-output=nolto-rel', str(original), '-o', str(dest)]
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
                commands.append(command)
                if sha(dest.read_bytes()) != NATIVE_SHA[name]:
                    raise ValueError('Compiled native member requires SDK/toolchain review: ' + name)
            else:
                dest.write_bytes(trace[name])
            files.append(dest)
        candidate = folder / 'compact.a'
        shutil.copy2(source, candidate)
        subprocess.run([str(ar), 'rDs', str(candidate), *map(str, files)],
                       check=True, capture_output=True, text=True, timeout=30)
        report = dict(kind=KIND, source=str(source), source_sha256=PRODUCTION_SHA,
                      trace_source=str(trace_source), trace_source_sha256=ARCHIVE_SHA,
                      archive=str(candidate), archive_sha256=sha(candidate.read_bytes()),
                      native_compilation_members=list(NATIVE_SHA), trace_members=list(TRACE_MEMBERS),
                      trace_derivation=trace_proof, commands=commands, hardware_qualified=False,
                      scope='Pinned SDK derivation; no instruction patches or physical qualification')
        verify_report(report, ar)
        if output.exists():
            if output.read_bytes() != candidate.read_bytes():
                raise ValueError('Differing derived SDK output preserved; use a fresh build directory')
        else:
            with output.open('xb') as stream:
                stream.write(candidate.read_bytes())
        report['archive'] = str(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'trace-archive', 'output', 'ar', 'objcopy', 'cc', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for path in (args.archive, args.trace_archive, args.output):
        different_source(path, args.report)
    report = prepare_archive(args.archive, args.trace_archive, args.output, args.ar, args.objcopy, args.cc)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(kind=KIND, archive_sha256=report['archive_sha256'])))


if __name__ == '__main__':
    main()
