#!/usr/bin/env python3
"""Build conservative target-oriented candidate lists from Ghidra exports."""

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re


TARGETS = {
    "button": {
        "peripherals": ("GPIO", "GPIOTE"),
        "keywords": ("button", "keypress", "key press", "switch", "debounce"),
    },
    "led": {
        "peripherals": ("GPIO", "PWM"),
        "keywords": ("led", "status light", "indicator"),
    },
    "timing": {
        "peripherals": ("TIMER", "RTC", "PPI", "GPIOTE"),
        "keywords": ("timer", "timeout", "delay", "latency", "debounce", "tick"),
    },
    "secondary_mcu": {
        "peripherals": ("UART", "UARTE", "SPI", "SPIM", "TWI", "TWIM"),
        "keywords": ("uart", "serial", "spi", "twi", "coprocessor", "mcu"),
    },
    "fault_watchdog": {
        "peripherals": ("WDT",),
        "keywords": ("fault", "watchdog", "wdt", "error", "overcurrent", "thermal"),
    },
}

NEXT_VALIDATION = {
    "button": "Correlate GPIO/GPIOTE activity with physical button presses.",
    "led": "Correlate GPIO/PWM activity with each visible LED state.",
    "timing": "Measure event-to-action latency and timer activity on hardware.",
    "secondary_mcu": "Capture candidate bus pins during commands and state changes.",
    "fault_watchdog": "Induce only documented safe faults and observe status traffic.",
}

MISSING_EVIDENCE = {
    "button": "GPIO candidates overlap LED/general board support; physical-event correlation is required.",
    "led": "GPIO candidates overlap button/general board support and no direct LED string anchor was found.",
    "timing": "Timer ownership and its relationship to local-input latency are not established.",
    "secondary_mcu": "No function-owned reference to configured UART/SPI/TWI ranges was exported; GPIO framing or an undiscovered reference remains possible.",
    "fault_watchdog": "WDT register references exist outside Ghidra-defined functions; application fault semantics remain unknown.",
}


@dataclass(frozen=True)
class SignalScore:
    score: int
    signals: tuple
    classification: str


def matches_keyword(target, text):
    lowered = text.lower()
    if target == "button" and "buttonless" in lowered:
        return False
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])", lowered)
        for keyword in TARGETS[target]["keywords"]
    )


def _relevant(target, peripheral):
    return any(family in peripheral for family in TARGETS[target]["peripherals"])


def score_signals(
    target, *, memory_peripherals, scalar_peripherals, strings, neighbor, match_score
):
    memory = sorted({item for item in memory_peripherals if _relevant(target, item)})
    scalars = sorted({item for item in scalar_peripherals if _relevant(target, item)})
    keyword_hits = sorted({
        keyword
        for value in strings
        for keyword in TARGETS[target]["keywords"]
        if matches_keyword(target, value)
        and re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])", value.lower())
    })
    signals = [f"memory:{item}" for item in memory]
    signals.extend(f"scalar:{item}" for item in scalars)
    signals.extend(f"string:{item}" for item in keyword_hits)
    score = min(15, 5 * len(memory)) + min(3, len(scalars)) + min(15, 5 * len(keyword_hits))
    if neighbor:
        score += 2
        signals.append("call_neighbor")
    if match_score:
        score += min(5, round(match_score / 20))
        signals.append(f"cross_firmware_match:{match_score}")
    independent = int(bool(memory)) + int(bool(keyword_hits))
    classification = "STRONG INFERENCE" if independent >= 2 else "HYPOTHESIS"
    return SignalScore(score, tuple(signals), classification)


def read_tsv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))


def load_firmware(repo, firmware):
    base = repo / "analysis" / firmware / "generated"
    strings = {row["address"]: row["value"] for row in read_tsv(base / "strings.tsv")}
    by_function = {}
    for row in read_tsv(base / "string_xrefs.tsv"):
        address = row["function_address"]
        if address:
            by_function.setdefault(address, {"memory": set(), "scalar": set(), "strings": []})
            by_function[address]["strings"].append(strings[row["string_address"]])
    for row in read_tsv(base / "peripheral_refs.tsv"):
        address = row["function_address"]
        if not address:
            continue
        data = by_function.setdefault(address, {"memory": set(), "scalar": set(), "strings": []})
        key = "memory" if row["evidence"] == "memory_reference" else "scalar"
        data[key].add(row["peripheral"])
    neighbors = {}
    for row in read_tsv(base / "call_edges.tsv"):
        neighbors.setdefault(row["caller"], set()).add(row["callee"])
        neighbors.setdefault(row["callee"], set()).add(row["caller"])
    return by_function, neighbors


def load_matches(repo):
    mesh = {}
    zigbee = {}
    for row in read_tsv(repo / "analysis/comparison/generated/function_matches.tsv"):
        score = int(row["score"])
        mesh.setdefault(row["mesh_address"], []).append((row["zigbee_address"], score))
        zigbee.setdefault(row["zigbee_address"], []).append((row["mesh_address"], score))
    return mesh, zigbee


def build_candidates(repo):
    data = {}
    neighbors = {}
    for firmware in ("mesh", "zigbee"):
        data[firmware], neighbors[firmware] = load_firmware(repo, firmware)
    matches = dict(zip(("mesh", "zigbee"), load_matches(repo)))
    base_scores = {}
    for firmware in ("mesh", "zigbee"):
        for address, evidence in data[firmware].items():
            for target in TARGETS:
                base_scores[(firmware, address, target)] = score_signals(
                    target,
                    memory_peripherals=evidence["memory"],
                    scalar_peripherals=evidence["scalar"], strings=evidence["strings"],
                    neighbor=False, match_score=0,
                ).score

    output = []
    for firmware in ("mesh", "zigbee"):
        candidate_addresses = set(data[firmware])
        for address in list(candidate_addresses):
            candidate_addresses.update(neighbors[firmware].get(address, ()))
        other = "zigbee" if firmware == "mesh" else "mesh"
        for address in candidate_addresses:
            evidence = data[firmware].get(
                address, {"memory": set(), "scalar": set(), "strings": []}
            )
            for target in TARGETS:
                neighbor = any(
                    base_scores.get((firmware, adjacent, target), 0) >= 5
                    for adjacent in neighbors[firmware].get(address, ())
                )
                match_score = max(
                    (
                        score for counterpart, score in matches[firmware].get(address, ())
                        if base_scores.get((other, counterpart, target), 0) > 0
                    ),
                    default=0,
                )
                result = score_signals(
                    target,
                    memory_peripherals=evidence["memory"],
                    scalar_peripherals=evidence["scalar"], strings=evidence["strings"],
                    neighbor=neighbor, match_score=match_score,
                )
                if result.score:
                    output.append({
                        "target": target, "firmware": firmware,
                        "function_address": address, "score": result.score,
                        "signals": ";".join(result.signals),
                        "classification": result.classification,
                        "next_validation": NEXT_VALIDATION[target],
                    })
    output.sort(key=lambda row: (
        row["target"], row["firmware"], -row["score"], int(row["function_address"], 16)
    ))
    limited = []
    counts = {}
    for row in output:
        key = (row["target"], row["firmware"])
        if counts.get(key, 0) < 20:
            limited.append(row)
            counts[key] = counts.get(key, 0) + 1
    return limited


def write_outputs(repo, rows):
    generated = repo / "analysis/comparison/generated/priority_candidates.tsv"
    generated.parent.mkdir(parents=True, exist_ok=True)
    fields = ["target", "firmware", "function_address", "score", "signals", "classification", "next_validation"]
    with generated.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", quoting=csv.QUOTE_NONE, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    report = repo / "analysis/comparison/priority-targets.md"
    lines = [
        "# Priority Firmware Targets", "",
        "This is an automated triage, not semantic confirmation. A **STRONG INFERENCE**",
        "requires both a direct relevant memory reference and an independent string/XREF",
        "signal. Cross-firmware similarity and call proximity only adjust ranking.", "",
    ]
    for target in TARGETS:
        lines.extend((f"## {target}", ""))
        for firmware in ("mesh", "zigbee"):
            selected = [row for row in rows if row["target"] == target and row["firmware"] == firmware][:10]
            lines.extend((f"### {firmware.capitalize()}", "", "| Address | Score | Classification | Signals |", "|---|---:|---|---|"))
            lines.extend(
                f"| `{row['function_address']}` | {row['score']} | {row['classification']} | `{row['signals']}` |"
                for row in selected
            )
            lines.append("")
        lines.extend((f"Missing evidence: {MISSING_EVIDENCE[target]}", ""))
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    repo = args.repo.resolve()
    rows = build_candidates(repo)
    write_outputs(repo, rows)
    print(f"wrote {len(rows)} priority candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
