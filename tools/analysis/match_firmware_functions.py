#!/usr/bin/env python3
"""Rank structural matches between Mesh and Zigbee Ghidra functions."""

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FunctionFeatures:
    address: str
    byte_size: int
    instruction_count: int
    basic_blocks: int
    cyclomatic: int
    calls: int
    unique_constants: int
    mnemonic_sha256: str
    exact_bytes_sha256: str


@dataclass(frozen=True)
class MatchResult:
    mesh_address: str
    zigbee_address: str
    score: int
    exact_bytes: bool
    mnemonic: bool
    structure: int
    calls: int
    constants: int
    evidence: tuple
    conflicts: tuple


def _similarity(left: int, right: int) -> float:
    maximum = max(left, right, 1)
    return max(0.0, 1.0 - abs(left - right) / maximum)


def _ratio(left: int, right: int) -> float:
    low = max(min(left, right), 1)
    return max(left, right) / low


def score_pair(mesh: FunctionFeatures, zigbee: FunctionFeatures) -> MatchResult:
    evidence = []
    conflicts = []
    exact = (
        mesh.byte_size == zigbee.byte_size
        and mesh.exact_bytes_sha256 == zigbee.exact_bytes_sha256
    )
    mnemonic = (
        mesh.instruction_count == zigbee.instruction_count
        and mesh.mnemonic_sha256 == zigbee.mnemonic_sha256
    )
    score = 0
    if exact:
        score += 55
        evidence.append("exact_bytes")
    if mnemonic:
        score += 25
        evidence.append("mnemonic_sequence")

    structural_values = (
        _similarity(mesh.byte_size, zigbee.byte_size),
        _similarity(mesh.instruction_count, zigbee.instruction_count),
        _similarity(mesh.basic_blocks, zigbee.basic_blocks),
        _similarity(mesh.cyclomatic, zigbee.cyclomatic),
    )
    structure = round(15 * sum(structural_values) / len(structural_values))
    call_score = round(5 * _similarity(mesh.calls, zigbee.calls))
    constant_score = round(
        5 * _similarity(mesh.unique_constants, zigbee.unique_constants)
    )
    score += structure + call_score + constant_score
    if structure >= 12:
        evidence.append("similar_structure")
    if call_score >= 4:
        evidence.append("similar_call_count")
    if constant_score >= 4:
        evidence.append("similar_constant_count")

    if _ratio(mesh.byte_size, zigbee.byte_size) > 2.5:
        score -= 15
        conflicts.append("size_ratio")
    if _ratio(mesh.instruction_count, zigbee.instruction_count) > 2.5:
        score -= 10
        conflicts.append("instruction_ratio")
    score = max(0, min(100, score))
    return MatchResult(
        mesh.address, zigbee.address, score, exact, mnemonic, structure,
        call_score, constant_score, tuple(evidence), tuple(conflicts),
    )


def rank_candidates(mesh_rows, zigbee_rows, limit_per_function=5):
    matches = []
    for mesh in mesh_rows:
        candidates = [score_pair(mesh, zigbee) for zigbee in zigbee_rows]
        candidates.sort(key=lambda row: (-row.score, int(row.zigbee_address, 16)))
        matches.extend(candidates[:limit_per_function])
    matches.sort(
        key=lambda row: (-row.score, int(row.mesh_address, 16), int(row.zigbee_address, 16))
    )
    return matches


def read_features(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        return [
            FunctionFeatures(
                address=row["address"],
                byte_size=int(row["byte_size"]),
                instruction_count=int(row["instruction_count"]),
                basic_blocks=int(row["basic_blocks"]),
                cyclomatic=int(row["cyclomatic"]),
                calls=int(row["calls"]),
                unique_constants=int(row["unique_constants"]),
                mnemonic_sha256=row["mnemonic_sha256"],
                exact_bytes_sha256=row["exact_bytes_sha256"],
            )
            for row in reader
        ]


def write_matches(path: Path, matches):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "mesh_address", "zigbee_address", "score", "exact_bytes", "mnemonic",
        "structure", "calls", "constants", "evidence", "conflicts",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", quoting=csv.QUOTE_NONE,
            lineterminator="\n", extrasaction="raise",
        )
        writer.writeheader()
        for match in matches:
            writer.writerow({
                "mesh_address": match.mesh_address,
                "zigbee_address": match.zigbee_address,
                "score": match.score,
                "exact_bytes": str(match.exact_bytes).lower(),
                "mnemonic": str(match.mnemonic).lower(),
                "structure": match.structure,
                "calls": match.calls,
                "constants": match.constants,
                "evidence": ";".join(match.evidence),
                "conflicts": ";".join(match.conflicts),
            })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    repo = args.repo.resolve()
    mesh = read_features(repo / "analysis/mesh/generated/function_fingerprints.tsv")
    zigbee = read_features(repo / "analysis/zigbee/generated/function_fingerprints.tsv")
    output = repo / "analysis/comparison/generated/function_matches.tsv"
    write_matches(output, rank_candidates(mesh, zigbee, args.limit))
    print(f"wrote {output.relative_to(repo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
