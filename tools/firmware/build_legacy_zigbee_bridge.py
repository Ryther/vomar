#!/usr/bin/env python3
"""Build a LOCAL signed profile1 bridge to the exact multi-bond common recovery.

Snapshots sources and pinned public inputs. Never contacts hardware, a radio or
an update service. The result remains an unqualified local candidate.
"""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from tools.firmware.bond_capacity import validate_bond_capacity
from tools.firmware.build_ota_migration import check_slot, validate_split_migration_config
from tools.firmware.loader_runtime_contract import LEGACY_KIND, validate_records
from tools.firmware.package_common_android_update_v3 import verify_image
from tools.firmware.package_zigbee_ota import ENCODER_ADAPTER, image, stage_budget, version_tuple
from tools.firmware.toolchain_paths import toolchain_paths
from tools.firmware.validate_recovery import read_config, read_hex, validate_uicr_preservation

VERSION = "0.6.3"
LEGACY_RECOVERY_SHA256 = "041c68611b8fd426aaabd36d979112bebaeaad0f3b906c538bb6c21f739df03c"
CURRENT_MAIN_SHA256 = "b52dc31fa2587dd4f349fac355433a6d41ad2d6464d64c0633e14f549c9bd8c0"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _verify_signed(blob, parsed, key):
    unprotected = parsed["unprotected"]
    keyhash = hashlib.sha256(key.public_bytes(serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)).digest()
    digest = hashlib.sha256(blob[:parsed["authenticated_end"]]).digest()
    if (set(unprotected) != {1, 0x10, 0x22} or unprotected[1] != keyhash
            or unprotected[0x10] != digest):
        raise ValueError("image key/hash/TLV mismatch")
    try:
        key.verify(unprotected[0x22], digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("invalid image signature") from exc
    return digest.hex()


def legacy_image_metadata(blob, key, *, base, capacity, version, require_target=False):
    """Authenticate ordinary legacy-role-none bytes; old inputs may lack a0."""
    parsed = check_slot(blob, base, capacity, version)
    protected = parsed["protected"]
    if (struct.unpack_from("<I", blob, 4)[0] or struct.unpack_from("<I", blob, 28)[0]
            or set(protected) - {0x50, 0xa0}
            or (0x50 in protected and len(protected[0x50]) != 4)
            or protected.get(0xa0, b"VIMAR30805\x01") != b"VIMAR30805\x01"
            or (require_target and protected.get(0xa0) != b"VIMAR30805\x01")):
        raise ValueError("legacy image requires profile1 target and no role TLV")
    digest = _verify_signed(blob, parsed, key)
    return dict(size=len(blob), fileSha256=sha(blob), signedRegionSha256=digest,
        version=version, wireVersion=list(version_tuple(parsed["version"])), profile=1)


def validate_candidate(manifest_path, key):
    """Freeze and authenticate the manifest's recovery and native config bytes."""
    path = Path(manifest_path).resolve()
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("kind") != "unqualified-typed-common-candidate"
            or manifest.get("model") != "VIMAR30805"
            or manifest.get("versions", {}).get("recovery") != "0.8.3"):
        raise ValueError("expected the matched multi-bond recovery0.8.3 candidate")
    records = validate_records(manifest["loader_contracts"])
    allowed = sorted(record.sha256 for record in records if record.kind == LEGACY_KIND)
    if len(allowed) != 3:
        raise ValueError("bridge requires exactly three finite legacy loader records")
    reference = manifest["artifacts"]["recovery"]
    recovery_path = (path.parent / reference["path"]).resolve()
    recovery = recovery_path.read_bytes()
    if sha(recovery) != reference["sha256"] or len(recovery) != reference["size"]:
        raise ValueError("candidate recovery SHA256/size mismatch")
    metadata = verify_image(recovery, key, "recovery")
    if metadata["wireVersion"] != [0, 8, 3, 0]:
        raise ValueError("replacement recovery version mismatch")
    config_path = path.parent / "artifacts/recovery.config"
    config = config_path.read_bytes()
    if sha(config) != manifest["native"]["recovery"]["config_sha256"]:
        raise ValueError("candidate recovery config SHA256 mismatch")
    validate_bond_capacity(dict(line.split("=", 1) for line in config.decode().splitlines()
        if line.startswith("CONFIG_") and "=" in line))
    return dict(recovery_bytes=recovery, recovery_config_bytes=config,
        recovery_metadata=metadata, allowed_loaders=allowed,
        sources=dict(candidate_manifest=dict(path=str(path), sha256=sha(raw), size=len(raw)),
            recovery=dict(path=str(recovery_path), sha256=sha(recovery), size=len(recovery)),
            recovery_config=dict(path=str(config_path), sha256=sha(config), size=len(config))))


def legacy_carrier(compressed, ordinary, key):
    """Authenticate and decompress exact bridge bytes before wrapping Zigbee OTA."""
    metadata = legacy_image_metadata(ordinary, key, base=0xc000, capacity=0xa2000,
        version=VERSION, require_target=True)
    plain, parsed = image(ordinary), image(compressed)
    protected = parsed["protected"]
    expected = {0x70, 0x71, 0x72, 0xa0} | ({0x50} if 0x50 in plain["protected"] else set())
    if (parsed["flags"] != 0xc00 or set(protected) != expected
            or protected[0xa0] != b"VIMAR30805\x01"
            or protected.get(0x50) != plain["protected"].get(0x50)
            or protected[0x70] != struct.pack("<I", plain["size"])
            or protected[0x71] != bytes.fromhex(metadata["signedRegionSha256"])):
        raise ValueError("legacy compressed target/role/reconstruction metadata mismatch")
    _verify_signed(compressed, parsed, key)
    try:
        key.verify(protected[0x72], protected[0x71], ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("invalid reconstructed image signature") from exc
    normalized = bytearray(compressed[:512])
    struct.pack_into("<H", normalized, 10, struct.unpack_from("<H", ordinary, 10)[0])
    struct.pack_into("<II", normalized, 12, plain["size"], 0)
    if bytes(normalized) != ordinary[:512]:
        raise ValueError("compressed ordinary header mismatch")
    stream = compressed[512:512 + parsed["size"]]
    if stream[:2] != b"\x06\x5d":
        raise ValueError("unsupported SDK compression parameters")
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_ARMTHUMB}, {"id": lzma.FILTER_LZMA2, "dict_size": 32768}])
    try:
        decoded = decoder.decompress(stream[2:], max_length=plain["size"] + 1)
    except lzma.LZMAError as exc:
        raise ValueError("invalid compressed stream") from exc
    if (not decoder.eof or decoder.unused_data
            or decoded != ordinary[512:512 + plain["size"]]):
        raise ValueError("compressed carrier does not reconstruct exact bridge payload")
    ota = struct.pack("<IHHHHHIH32sIHHHI", 0x0beef11e, 0x100, 60, 4,
        0xfff1, 0x3085, 0x00060300, 2, b"Vimar30805 legacy bridge OTA", 66 + len(compressed),
        1, 1, 0, len(compressed)) + compressed
    return ota, dict(metadata, manufacturerCode=0xfff1, imageType=0x3085, fileVersion=0x00060300,
        otaSha256=sha(ota), otaSize=len(ota))


def _digest_array(name, digest):
    return "static const uint8_t " + name + "[32]={" + ",".join(
        "0x" + digest[i:i + 2] for i in range(0, 64, 2)) + "};\n"


def _write_headers(generated, validated, legacy_metadata):
    recovery = validated["recovery_bytes"]
    allowed = validated["allowed_loaders"]
    (generated / "common_platform.h").write_text("#include <stdint.h>\n#define MIGRATION_ALLOWED_LOADER_COUNT 3u\n"
        + "static const uint8_t migration_allowed_loaders[][32]={\n" + ",\n".join(
            "{" + ",".join("0x" + digest[i:i + 2] for i in range(0, 64, 2)) + "}" for digest in allowed)
        + "};\n" + _digest_array("expected_recovery_sha256", sha(recovery)))
    (generated / "recovery_blob.h").write_text("#include <stdint.h>\n#define RECOVERY_BLOB_SIZE "
        + str(len(recovery)) + "u\nstatic const uint8_t recovery_blob[] __attribute__((aligned(4)))={\n"
        + "\n".join(",".join("0x%02x" % value for value in recovery[i:i + 16]) + ","
                    for i in range(0, len(recovery), 16)) + "};\n")
    (generated / "legacy_recovery_policy.h").write_text("#include <stdint.h>\n"
        + _digest_array("legacy_source_recovery_digest", legacy_metadata["signedRegionSha256"]))


def build(output, candidate_manifest, legacy_recovery_signed, current_main_signed=None):
    paths = toolchain_paths()
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(ROOT / "inputs"):
        raise ValueError("bridge output must be NEW and outside immutable inputs")
    if current_main_signed is None:
        raise ValueError("explicit current MAIN0.5.5 signed image is required (--current-main)")
    public_bytes = paths["public_key"].read_bytes()
    public = serialization.load_pem_public_key(public_bytes)
    validated = validate_candidate(candidate_manifest, public)
    legacy_path = Path(legacy_recovery_signed).resolve()
    legacy = legacy_path.read_bytes()
    if sha(legacy) != LEGACY_RECOVERY_SHA256:
        raise ValueError("legacy recovery differs from the exact frozen0.7.1 input")
    legacy_metadata = legacy_image_metadata(legacy, public, base=0xb0000, capacity=0x40000, version="0.7.1")
    current_path = Path(current_main_signed).resolve()
    current = current_path.read_bytes()
    if sha(current) != CURRENT_MAIN_SHA256:
        raise ValueError("current MAIN differs from exact frozen0.5.5 stage authority")
    current_metadata = legacy_image_metadata(current, public, base=0xc000, capacity=0xa2000, version="0.5.5")
    output.mkdir(parents=True)
    output = output.resolve()
    generated, artifacts = output / "generated", output / "artifacts"
    generated.mkdir(); artifacts.mkdir()
    manifest_path = output / "bridge-manifest.json"
    sources = dict(validated["sources"], legacy_recovery=dict(path=str(legacy_path), sha256=sha(legacy), size=len(legacy)),
        current_main=dict(path=str(current_path), sha256=sha(current), size=len(current)),
        verification_public_key=dict(path=str(paths["public_key"]), sha256=sha(public_bytes), size=len(public_bytes)))
    report = dict(schema_version=1, kind="unqualified-legacy-zigbee-bridge", model="VIMAR30805",
        version=VERSION, ota_profile=1, role_tlv=None, hardware_qualified=False, deployable=False,
        qualified_release_zip=False, status="snapshot", sources=sources, commands=[], artifacts={},
        allowed_legacy_loaders=validated["allowed_loaders"], target_recovery=validated["recovery_metadata"],
        source_recovery=legacy_metadata, source_main=current_metadata,
        transformations=["copy firmware excluding keys and build caches", "snapshot ota_migration/VERSION=0.6.3",
            "exact signed recovery to aligned immutable C array", "finite legacy loader full hashes and target full-file hash to C constants",
            "exact legacy recovery signed-region hash to C admission constant", "ordinary profile1/no-role P256 signing",
            "LZMA2 ARMThumb dict32768 lc3 lp0 pb2 alignment1 and profile1/no-role signing", "single-subelement Zigbee OTA envelope"],
        pending_checks=["frozen legacy verifier acceptance and SDK decompression", "independent artifact/source review",
            "physical PC plus Android pairing without deletion", "physical migration and interrupted-copy qualification"])

    def save():
        manifest_path.write_text(json.dumps(report, indent=2) + "\n")

    def run(argv, name, cwd=ROOT):
        argv = list(map(str, argv))
        report["commands"].append(dict(argv=argv, cwd=str(cwd), log=name))
        report["status"] = "running " + name
        save()
        print("start " + name, flush=True)
        env = os.environ.copy()
        env["PATH"] = str(paths["west"].parent) + ":" + env["PATH"]
        env["CMAKE_BUILD_PARALLEL_LEVEL"] = "2"
        with (output / name).open("w") as log:
            subprocess.run(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        print("pass " + name, flush=True)

    firmware = output / "source/firmware"
    shutil.copytree(ROOT / "firmware", firmware, ignore=shutil.ignore_patterns("keys", "__pycache__", "build", ".pytest_cache"))
    report["workspace_source_sha256"] = {str(p.relative_to(output / "source")): sha(p.read_bytes())
        for p in sorted(firmware.rglob("*")) if p.is_file()}
    (firmware / "ota_migration/VERSION").write_text("VERSION_MAJOR = 0\nVERSION_MINOR = 6\nPATCHLEVEL = 3\nVERSION_TWEAK = 0\nEXTRAVERSION =\n")
    report["snapshot_source_sha256"] = {str(p.relative_to(output / "source")): sha(p.read_bytes())
        for p in sorted(firmware.rglob("*")) if p.is_file()}
    tool_sources = output / "tool-source"
    tool_sources.mkdir()
    for relative in ("build_legacy_zigbee_bridge.py", "bond_capacity.py", "build_ota_migration.py", "loader_runtime_contract.py",
            "package_common_android_update_v3.py", "package_zigbee_ota.py", "imgtool_bt2_adapter.py", "toolchain_paths.py", "validate_recovery.py"):
        shutil.copy2(ROOT / "tools/firmware" / relative, tool_sources / relative)
    report["tool_source_sha256"] = {p.name: sha(p.read_bytes()) for p in sorted(tool_sources.iterdir())}
    report["sdk_signing_source_sha256"] = {str(p.relative_to(paths["sdk"])): sha(p.read_bytes()) for p in (
        paths["imgtool"], paths["imgtool"].parent / "imgtool/main.py", paths["imgtool"].parent / "imgtool/image.py")}
    _write_headers(generated, validated, legacy_metadata)
    target = generated / "target-profile1.bin"
    target.write_bytes(b"VIMAR30805\x01")
    for name, blob in (("target-recovery.signed.bin", validated["recovery_bytes"]),
            ("target-recovery.config", validated["recovery_config_bytes"]),
            ("legacy-recovery.signed.bin", legacy), ("current-main.signed.bin", current),
            ("verification-public.pem", public_bytes)):
        (output / name).write_bytes(blob)
    config_path = generated / "bridge.conf"
    config_path.write_text("\n".join([
        "CONFIG_MIGRATION_COMMON=y", "CONFIG_MIGRATION_LEGACY_ZIGBEE_ENTRY=y", "CONFIG_VIMAR_LOADER_RUNTIME_V2=n",
        "CONFIG_VIMAR_OTA_SPLIT_STAGING=y", "CONFIG_VIMAR_P031_PROTECTION=y", "CONFIG_SETTINGS=y", "CONFIG_NVS=y",
        "CONFIG_SETTINGS_NVS=y", "CONFIG_SOC_FLASH_NRF_PARTIAL_ERASE_MS=6", "CONFIG_MAIN_STACK_SIZE=12288",
        'CONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""', "CONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n", "CONFIG_MIGRATION_STAGE_PROBE=n"]) + "\n")
    report["generated_sha256"] = {p.name: sha(p.read_bytes()) for p in sorted(generated.iterdir())}
    save()
    for filename in ("target-recovery.signed.bin", "legacy-recovery.signed.bin", "current-main.signed.bin"):
        run([paths["python"], paths["imgtool"], "verify", "-k", output / "verification-public.pem", output / filename], filename + "-verify.log")
    native = output / "build"
    run([paths["west"], "build", "--pristine", "--no-sysbuild", "-b", "nrf52840dk/nrf52840",
        firmware / "ota_migration", "-d", native, "--target", "zephyr/zephyr.elf", "--",
        "-DGENERATED_DIR=" + str(generated), "-DEXTRA_CONF_FILE=" + ";".join(map(str, [firmware / "research/vimar-candidate.conf", config_path])),
        "-DDTC_OVERLAY_FILE=" + ";".join(map(str, [firmware / "boards/nrf52840dk_nrf52840_ota.overlay",
            firmware / "research/vimar-candidate.overlay"]))], "bridge-build.log", paths["sdk"])
    config = read_config(native / "zephyr/.config")
    validate_split_migration_config(config)
    if (any(config.get(key) != "y" for key in ("CONFIG_MIGRATION_COMMON", "CONFIG_MIGRATION_LEGACY_ZIGBEE_ENTRY"))
            or any(config.get(key) == "y" for key in ("CONFIG_BT", "CONFIG_VIMAR_LOADER_RUNTIME_V2", "CONFIG_MIGRATION_STAGE_PROBE", "CONFIG_NORDIC_QSPI_NOR"))
            or config.get("CONFIG_MCUBOOT_SIGNATURE_KEY_FILE") != '""'
            or config.get("CONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE") == "y"
            or int(config.get("CONFIG_MAIN_STACK_SIZE", "0")) < 12288):
        raise ValueError("resolved bridge configuration differs from required isolated legacy entry")
    if any((native / "zephyr").glob("*.signed.*")):
        raise ValueError("unexpected native signing")
    defines = set(re.findall(r"-D([A-Za-z0-9_]+)", (native / "build.ninja").read_text()))
    validate_uicr_preservation({"bridge": config}, {"bridge": defines})
    mapped = read_hex(native / "zephyr/zephyr.hex")
    if not mapped or min(mapped) != 0xc000 or max(mapped) >= 0xae000:
        raise ValueError("bridge HEX outside bounded primary area")
    from elftools.elf.elffile import ELFFile
    with (native / "zephyr/zephyr.elf").open("rb") as stream:
        elf = ELFFile(stream)
        if elf["e_machine"] != "EM_ARM": raise ValueError("native bridge is not ARM")
        segments = [dict(start=s["p_paddr"], end=s["p_paddr"] + s["p_filesz"])
            for s in elf.iter_segments() if s["p_type"] == "PT_LOAD" and s["p_filesz"] and s["p_paddr"] < 0x100000]
    if not segments or any(not 0xc000 <= s["start"] < s["end"] <= 0xae000 for s in segments):
        raise ValueError("bridge ELF ROM outside bounded primary area")
    for suffix in ("bin", "elf", "hex"):
        shutil.copy2(native / ("zephyr/zephyr." + suffix), artifacts / ("bridge.unsigned." + suffix))
    shutil.copy2(native / "zephyr/.config", artifacts / "bridge.config")
    unsigned = artifacts / "bridge.unsigned.bin"
    recovery = validated["recovery_bytes"]
    offset = unsigned.read_bytes().find(recovery)
    if offset < 0 or unsigned.read_bytes().count(recovery) != 1:
        raise ValueError("exact replacement recovery not embedded once in linked bridge")
    report["native"] = dict(config_sha256=sha((artifacts / "bridge.config").read_bytes()), rom_segments=segments,
        unsigned_size=unsigned.stat().st_size, capacity=0xa2000, embedded_recovery=dict(offset=offset, size=len(recovery), sha256=sha(recovery)))
    signed = artifacts / "bridge-0.6.3.signed.bin"
    compressed = artifacts / "bridge-0.6.3.compressed.bin"
    common = ["sign", "--version", VERSION, "--header-size", "512", "--slot-size", "0xa2000",
        "--overwrite-only", "-k", paths["private_key"]]
    run([paths["python"], paths["imgtool"], *common, "--align", "4", "--custom-tlv-file", "0xa0", target, unsigned, signed], "bridge-sign.log")
    run([paths["python"], ENCODER_ADAPTER, paths["imgtool"], *common, "--align", "1", "--compression", "lzma2armthumb",
        "--compression-lzma-dictsize", "32768", "--compression-lzma-lp", "0", "--compression-lzma-lc", "3",
        "--compression-lzma-pb", "2", "--custom-tlv-file", "0xa0", target, unsigned, compressed], "bridge-compress-sign.log")
    for artifact in (signed, compressed):
        run([paths["python"], paths["imgtool"], "verify", "-k", output / "verification-public.pem", artifact], artifact.name + "-verify.log")
    ota, metadata = legacy_carrier(compressed.read_bytes(), signed.read_bytes(), public)
    (artifacts / "bridge-0.6.3.ota").write_bytes(ota)
    report["ota"] = dict(metadata=metadata, budget=stage_budget(len(current), compressed.stat().st_size, signed.stat().st_size))
    for artifact in sorted(artifacts.iterdir()):
        report["artifacts"][artifact.name] = dict(path=str(artifact), sha256=sha(artifact.read_bytes()), size=artifact.stat().st_size)
    report["status"] = "built; local signed candidate only; frozen legacy decoder and physical qualification pending"
    save()
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--candidate-manifest", required=True, type=Path)
    parser.add_argument("--legacy-recovery", required=True, type=Path)
    parser.add_argument("--current-main", required=True, type=Path,
                        help="Exact frozen0.5.5 signed stage-authority image; SHA-256 remains pinned.")
    args = parser.parse_args()
    print(build(args.output, args.candidate_manifest, args.legacy_recovery, args.current_main))


if __name__ == "__main__":
    main()
