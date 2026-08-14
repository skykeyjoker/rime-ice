#!/usr/bin/env python3
"""Generate the audited radical-reading supplement from pinned official data."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import re
import sys
from typing import Iterable, Optional
import unicodedata
import urllib.request
import zipfile


UNICODE_VERSION = "17.0.0"
UNIHAN_URL = f"https://www.unicode.org/Public/{UNICODE_VERSION}/ucd/Unihan.zip"
UNIHAN_SHA256 = "f7a48b2b545acfaa77b2d607ae28747404ce02baefee16396c5d2d7a8ef34b5e"

CNS_RELEASE = "20260805"
CNS_PROPERTIES_URL = "https://www.cns11643.gov.tw/opendata/Properties.zip"
CNS_PROPERTIES_SHA256 = "3d56ef14cc8099893245dac58fe4718d2fa64812b9159352a98a4588ad3efa5c"
CNS_MAPPINGS_URL = "https://www.cns11643.gov.tw/opendata/MapingTables.zip"
CNS_MAPPINGS_SHA256 = "4502fcf7b433d679dee51127298929543ec7f4aa99be93cd219df1552bc3d2bf"

DIRECT_READING_PROPERTIES = (
    "kHanyuPinlu",
    "kTGHZ2013",
    "kXHC1983",
    "kHanyuPinyin",
    "kSMSZD2003Readings",
)
SAFE_VARIANT_PROPERTIES = {"kCompatibilityVariant", "kZVariant"}
ALLOWED_COMBINING_MARKS = {"\u0300", "\u0301", "\u0302", "\u0304", "\u0308", "\u030c"}
PLACEHOLDER_CNS_READINGS = {"mǒu"}
SPACING_TONE_MARKS = {"ˉ": "\u0304", "ˊ": "\u0301", "ˇ": "\u030c", "ˋ": "\u0300"}

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RADICAL_DICTIONARY = REPOSITORY_ROOT / "radical_pinyin.dict.yaml"
DEFAULT_BASE_DICTIONARY = REPOSITORY_ROOT / "kMandarin17.dict.yaml"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "radical_reading_supplement.dict.yaml"
DEFAULT_PROVENANCE = REPOSITORY_ROOT / "radical_reading_supplement.provenance.tsv"
DEFAULT_UNRESOLVED = REPOSITORY_ROOT / "radical_reading_supplement.unresolved.tsv"
DEFAULT_CONFLICTS = REPOSITORY_ROOT / "radical_reading_supplement.conflicts.tsv"

EXPECTED_METRICS = {
    "radical_scalars": 92539,
    "radical_unihan": 92487,
    "base_covered": 43208,
    "unihan_direct": 12,
    "unihan_variant": 12,
    "cns_direct": 25517,
    "post_cns_variant": 2,
    "supplement_characters": 25543,
    "supplement_rows": 31192,
    "multiple_readings": 4314,
    "total_covered": 68751,
    "unresolved": 23736,
}
EXPECTED_DICTIONARY_SHA256 = "67892c0a19525789ef5bcad35bf63bd823d581cdc50201a931eceebe30058c92"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def read_checked_source(path: Optional[Path], url: str, expected_hash: str, label: str) -> bytes:
    if path is not None:
        data = path.read_bytes()
    else:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "skykey-rime-ice-radical-reading-generator"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()

    actual_hash = sha256(data)
    if actual_hash != expected_hash:
        raise ValueError(
            f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        )
    return data


def validate_reading(reading: str, source: str) -> str:
    reading = reading.strip().lower()
    for spacing_mark, combining_mark in SPACING_TONE_MARKS.items():
        reading = reading.replace(spacing_mark, combining_mark)
    reading = unicodedata.normalize("NFC", reading)
    if not reading:
        raise ValueError(f"{source} contains an empty reading")
    for character in unicodedata.normalize("NFD", reading):
        if "a" <= character <= "z" or character in ALLOWED_COMBINING_MARKS:
            continue
        raise ValueError(f"{source} contains unsupported pinyin character {character!r}")
    return reading


def parse_rime_dictionary_scalars(path: Path) -> set[int]:
    in_body = False
    result: set[int] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip("\ufeff")
        if not in_body:
            if line == "...":
                in_body = True
            continue
        if not line or line.startswith("#"):
            continue
        text = line.split("\t", 1)[0]
        if len(text) == 1:
            result.add(ord(text))
    if not in_body:
        raise ValueError(f"{path} does not contain a Rime dictionary body marker")
    return result


def parse_rime_readings(path: Path) -> dict[int, tuple[str, ...]]:
    in_body = False
    readings: dict[int, list[str]] = defaultdict(list)
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip("\ufeff")
        if not in_body:
            if line == "...":
                in_body = True
            continue
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 2 or len(fields[0]) != 1:
            continue
        code_point = ord(fields[0])
        reading = validate_reading(fields[1], f"{path}:{line_number}")
        if reading not in readings[code_point]:
            readings[code_point].append(reading)
    if not in_body:
        raise ValueError(f"{path} does not contain a Rime dictionary body marker")
    return {code_point: tuple(values) for code_point, values in readings.items()}


@dataclass(frozen=True)
class UnihanData:
    all_code_points: set[int]
    properties: dict[str, dict[int, str]]
    variant_graph: dict[int, set[int]]


def parse_unihan(source: bytes) -> UnihanData:
    wanted_properties = {"kMandarin", *DIRECT_READING_PROPERTIES, *SAFE_VARIANT_PROPERTIES}
    properties: dict[str, dict[int, str]] = {name: {} for name in wanted_properties}
    all_code_points: set[int] = set()
    graph: dict[int, set[int]] = defaultdict(set)

    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        members = sorted(
            name for name in archive.namelist() if name.startswith("Unihan") and name.endswith(".txt")
        )
        if not members:
            raise ValueError("Unihan archive does not contain any Unihan*.txt members")
        for member in members:
            for line_number, line in enumerate(
                archive.read(member).decode("utf-8").splitlines(), start=1
            ):
                if not line or line.startswith("#"):
                    continue
                fields = line.split("\t")
                if len(fields) != 3 or not fields[0].startswith("U+"):
                    continue
                code_point = int(fields[0][2:], 16)
                all_code_points.add(code_point)
                property_name, value = fields[1], fields[2]
                if property_name not in wanted_properties:
                    continue
                if code_point in properties[property_name]:
                    raise ValueError(f"duplicate {property_name} at {member}:{line_number}")
                properties[property_name][code_point] = value
                if property_name in SAFE_VARIANT_PROPERTIES:
                    for target_text in re.findall(r"U\+([0-9A-Fa-f]{4,6})", value):
                        target = int(target_text, 16)
                        graph[code_point].add(target)
                        graph[target].add(code_point)

    return UnihanData(all_code_points, properties, dict(graph))


def parse_unihan_reading_value(property_name: str, value: str, code_point: int) -> tuple[str, ...]:
    raw_readings: list[str] = []
    if property_name == "kMandarin":
        values = value.split()
        if values:
            raw_readings.append(values[0])
    elif property_name == "kHanyuPinlu":
        raw_readings.extend(re.findall(r"([^\s()]+)\(\d+\)", value))
    elif property_name in {"kTGHZ2013", "kXHC1983", "kHanyuPinyin"}:
        for token in value.split():
            _, separator, readings = token.partition(":")
            if separator:
                raw_readings.extend(readings.split(","))
    elif property_name == "kSMSZD2003Readings":
        for token in value.split():
            mandarin, separator, _ = token.partition("粵")
            if separator:
                raw_readings.extend(mandarin.split(","))
    else:
        raise ValueError(f"unsupported Unihan reading property {property_name}")

    return ordered_unique(
        validate_reading(reading, f"U+{code_point:04X} {property_name}")
        for reading in raw_readings
        if reading
    )


def build_unihan_readings(
    unihan: UnihanData,
) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[str, ...]], dict[int, tuple[str, ...]]]:
    base: dict[int, tuple[str, ...]] = {}
    direct: dict[int, tuple[str, ...]] = {}
    direct_sources: dict[int, tuple[str, ...]] = {}

    for code_point, value in unihan.properties["kMandarin"].items():
        parsed = parse_unihan_reading_value("kMandarin", value, code_point)
        if not parsed:
            raise ValueError(f"U+{code_point:04X} has an empty kMandarin value")
        base[code_point] = parsed

    for code_point in sorted(unihan.all_code_points - base.keys()):
        readings: list[str] = []
        sources: list[str] = []
        for property_name in DIRECT_READING_PROPERTIES:
            value = unihan.properties[property_name].get(code_point)
            if value is None:
                continue
            parsed = parse_unihan_reading_value(property_name, value, code_point)
            for reading in parsed:
                if reading not in readings:
                    readings.append(reading)
            if parsed:
                sources.append(property_name)
        if readings:
            direct[code_point] = tuple(readings)
            direct_sources[code_point] = tuple(sources)

    return base, direct, direct_sources


@dataclass(frozen=True)
class CnsData:
    readings: dict[int, tuple[str, ...]]
    codes: dict[int, tuple[str, ...]]
    sources: dict[int, tuple[str, ...]]


def parse_cns(properties_source: bytes, mappings_source: bytes) -> CnsData:
    with zipfile.ZipFile(io.BytesIO(properties_source)) as properties_archive:
        pinyin_by_bopomofo: dict[str, str] = {}
        for line_number, line in enumerate(
            properties_archive.read("CNS_pinyin_2.txt").decode("utf-8-sig").splitlines(), 1
        ):
            if not line:
                continue
            fields = line.split("\t")
            if len(fields) < 2:
                raise ValueError(f"malformed CNS_pinyin_2.txt:{line_number}")
            pinyin_by_bopomofo[fields[0]] = validate_reading(
                fields[1], f"CNS_pinyin_2.txt:{line_number}"
            )

        readings_by_code: dict[str, list[str]] = defaultdict(list)
        unknown_bopomofo: set[str] = set()
        for line_number, line in enumerate(
            properties_archive.read("CNS_phonetic.txt").decode("utf-8-sig").splitlines(), 1
        ):
            if not line:
                continue
            fields = line.split("\t")
            if len(fields) != 2:
                raise ValueError(f"malformed CNS_phonetic.txt:{line_number}")
            code, bopomofo = fields
            pinyin = pinyin_by_bopomofo.get(bopomofo)
            if pinyin is None:
                unknown_bopomofo.add(bopomofo)
                continue
            if pinyin in PLACEHOLDER_CNS_READINGS:
                continue
            if pinyin not in readings_by_code[code]:
                readings_by_code[code].append(pinyin)

        if unknown_bopomofo:
            preview = ", ".join(sorted(unknown_bopomofo)[:5])
            raise ValueError(f"CNS phonetic forms missing from pinyin table: {preview}")

        source_by_code: dict[str, list[str]] = defaultdict(list)
        for line in properties_archive.read("CNS_source.txt").decode("utf-8-sig").splitlines():
            if not line:
                continue
            code, separator, description = line.partition("\t")
            if separator and description not in source_by_code[code]:
                source_by_code[code].append(description)

    mappings_by_code: dict[str, list[int]] = defaultdict(list)
    with zipfile.ZipFile(io.BytesIO(mappings_source)) as mappings_archive:
        members = sorted(
            name
            for name in mappings_archive.namelist()
            if name.startswith("Unicode/CNS2UNICODE_Unicode ") and name.endswith(".txt")
        )
        if not members:
            raise ValueError("CNS mappings archive does not contain Unicode mapping tables")
        for member in members:
            for line_number, line in enumerate(
                mappings_archive.read(member).decode("utf-8-sig").splitlines(), 1
            ):
                if not line:
                    continue
                fields = line.split("\t")
                if len(fields) != 2:
                    raise ValueError(f"malformed {member}:{line_number}")
                code, unicode_text = fields
                try:
                    code_point = int(unicode_text, 16)
                except ValueError as error:
                    raise ValueError(f"invalid Unicode value at {member}:{line_number}") from error
                if code_point not in mappings_by_code[code]:
                    mappings_by_code[code].append(code_point)

    readings: dict[int, list[str]] = defaultdict(list)
    codes: dict[int, list[str]] = defaultdict(list)
    sources: dict[int, list[str]] = defaultdict(list)
    for code, code_points in mappings_by_code.items():
        code_readings = readings_by_code.get(code)
        if not code_readings:
            continue
        for code_point in code_points:
            if code not in codes[code_point]:
                codes[code_point].append(code)
            for reading in code_readings:
                if reading not in readings[code_point]:
                    readings[code_point].append(reading)
            for description in source_by_code.get(code, ()):
                if description not in sources[code_point]:
                    sources[code_point].append(description)

    return CnsData(
        {code_point: tuple(values) for code_point, values in readings.items()},
        {code_point: tuple(values) for code_point, values in codes.items()},
        {code_point: tuple(values) for code_point, values in sources.items()},
    )


def variant_components(graph: dict[int, set[int]]) -> dict[int, tuple[int, ...]]:
    components: dict[int, tuple[int, ...]] = {}
    visited: set[int] = set()
    for start in sorted(graph):
        if start in visited:
            continue
        stack = [start]
        members: list[int] = []
        visited.add(start)
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbor in graph.get(current, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        frozen_members = tuple(sorted(members))
        for member in frozen_members:
            components[member] = frozen_members
    return components


def propagate_unanimous_variants(
    targets: Iterable[int],
    known: dict[int, tuple[str, ...]],
    components: dict[int, tuple[int, ...]],
) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[int, ...]], set[int]]:
    propagated: dict[int, tuple[str, ...]] = {}
    evidence: dict[int, tuple[int, ...]] = {}
    ambiguous: set[int] = set()
    for target in sorted(targets):
        members = components.get(target)
        if not members:
            continue
        readable_members = tuple(member for member in members if member in known)
        if not readable_members:
            continue
        distinct_values = {frozenset(known[member]) for member in readable_members}
        if len(distinct_values) != 1:
            ambiguous.add(target)
            continue
        first = readable_members[0]
        propagated[target] = known[first]
        evidence[target] = readable_members
    return propagated, evidence, ambiguous


@dataclass(frozen=True)
class SupplementEntry:
    readings: tuple[str, ...]
    tier: str
    references: tuple[str, ...]
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeneratedFiles:
    dictionary: bytes
    provenance: bytes
    unresolved: bytes
    conflicts: bytes
    metrics: dict[str, int]


def sanitize_tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def render_files(
    radical_scalars: set[int],
    unihan: UnihanData,
    base: dict[int, tuple[str, ...]],
    direct: dict[int, tuple[str, ...]],
    direct_sources: dict[int, tuple[str, ...]],
    cns: CnsData,
) -> GeneratedFiles:
    radical_unihan = radical_scalars & unihan.all_code_points
    components = variant_components(unihan.variant_graph)
    supplement: dict[int, SupplementEntry] = {}

    for code_point in sorted(radical_unihan - base.keys()):
        readings = direct.get(code_point)
        if readings:
            supplement[code_point] = SupplementEntry(
                readings,
                "unihan-direct",
                tuple(f"Unicode-17:{source}" for source in direct_sources[code_point]),
            )

    known_before_cns = dict(base)
    known_before_cns.update(direct)
    remaining = radical_unihan - base.keys() - supplement.keys()
    pre_variant, pre_evidence, pre_ambiguous = propagate_unanimous_variants(
        remaining, known_before_cns, components
    )
    for code_point, readings in pre_variant.items():
        supplement[code_point] = SupplementEntry(
            readings,
            "unihan-variant",
            tuple(f"Unicode-17:variant:U+{member:04X}" for member in pre_evidence[code_point]),
        )

    remaining = radical_unihan - base.keys() - supplement.keys()
    for code_point in sorted(remaining):
        readings = cns.readings.get(code_point)
        if readings:
            supplement[code_point] = SupplementEntry(
                readings,
                "cns11643",
                tuple(f"CNS-{CNS_RELEASE}:{code}" for code in cns.codes.get(code_point, ())),
                cns.sources.get(code_point, ()),
            )

    known_after_cns = dict(known_before_cns)
    for code_point, readings in cns.readings.items():
        if code_point not in known_after_cns:
            known_after_cns[code_point] = readings
    remaining = radical_unihan - base.keys() - supplement.keys()
    post_variant, post_evidence, post_ambiguous = propagate_unanimous_variants(
        remaining, known_after_cns, components
    )
    for code_point, readings in post_variant.items():
        supplement[code_point] = SupplementEntry(
            readings,
            "post-cns-variant",
            tuple(f"official-variant:U+{member:04X}" for member in post_evidence[code_point]),
        )

    overlap = set(supplement) & set(base)
    if overlap:
        preview = ", ".join(f"U+{code_point:04X}" for code_point in sorted(overlap)[:5])
        raise ValueError(f"supplement must not override kMandarin17: {preview}")

    unresolved = radical_unihan - base.keys() - supplement.keys()
    rows = sum(len(entry.readings) for entry in supplement.values())
    multiple_readings = sum(len(entry.readings) > 1 for entry in supplement.values())
    tier_counts = defaultdict(int)
    for entry in supplement.values():
        tier_counts[entry.tier] += 1
    metrics = {
        "radical_scalars": len(radical_scalars),
        "radical_unihan": len(radical_unihan),
        "base_covered": len(radical_unihan & base.keys()),
        "unihan_direct": tier_counts["unihan-direct"],
        "unihan_variant": tier_counts["unihan-variant"],
        "cns_direct": tier_counts["cns11643"],
        "post_cns_variant": tier_counts["post-cns-variant"],
        "supplement_characters": len(supplement),
        "supplement_rows": rows,
        "multiple_readings": multiple_readings,
        "total_covered": len(radical_unihan & base.keys()) + len(supplement),
        "unresolved": len(unresolved),
        "ambiguous_variants": len(pre_ambiguous | post_ambiguous),
    }

    for key, expected in EXPECTED_METRICS.items():
        actual = metrics[key]
        if actual != expected:
            raise ValueError(f"metric {key} changed: expected {expected}, got {actual}")

    expected_examples = {
        ord("𪹪"): ("è",),
        ord("𤌪"): ("yān",),
        ord("𢨋"): ("bó", "bèi"),
    }
    for code_point, expected in expected_examples.items():
        actual_entry = supplement.get(code_point)
        if actual_entry is None or actual_entry.readings != expected:
            raise ValueError(
                f"U+{code_point:04X} sample mismatch: expected {expected}, "
                f"got {None if actual_entry is None else actual_entry.readings}"
            )
    for character in ("𤊢", "𤈝"):
        if ord(character) not in unresolved:
            raise ValueError(f"U+{ord(character):04X} must stay unresolved after mǒu filtering")

    dictionary_header = f"""# Rime dictionary
# encoding: utf-8
#
# GENERATED FILE. DO NOT EDIT BY HAND.
# Generator: scripts/generate_radical_reading_supplement.py
# Unicode source: {UNIHAN_URL}
# Unicode source SHA-256: {UNIHAN_SHA256}
# Unicode Data Files and Software Copyright © 1991-2025 Unicode, Inc.
# CNS source release: {CNS_RELEASE}
# CNS Properties SHA-256: {CNS_PROPERTIES_SHA256}
# CNS mapping SHA-256: {CNS_MAPPINGS_SHA256}
# CNS attribution: Taiwan Ministry of Digital Affairs, CNS11643 Open Data
# Policy: fill only characters missing from kMandarin17; discard CNS mǒu placeholders
# Characters: {len(supplement)}
# Rows: {rows}
# Unicode license: https://www.unicode.org/license.txt
# CNS Open Government Data License: https://data.gov.tw/license

---
name: radical_reading_supplement
version: "{UNICODE_VERSION}+cns-{CNS_RELEASE}"
sort: original
use_preset_vocabulary: false
...

"""
    dictionary_body = "".join(
        f"{chr(code_point)}\t{reading}\n"
        for code_point, entry in sorted(supplement.items())
        for reading in entry.readings
    )
    dictionary = (dictionary_header + dictionary_body).encode("utf-8")
    dictionary_hash = sha256(dictionary)
    if dictionary_hash != EXPECTED_DICTIONARY_SHA256:
        raise ValueError(
            "generated dictionary SHA-256 changed: "
            f"expected {EXPECTED_DICTIONARY_SHA256}, got {dictionary_hash}"
        )

    provenance_lines = ["character\tcode_point\treadings\ttier\treferences\tdetails\n"]
    for code_point, entry in sorted(supplement.items()):
        provenance_lines.append(
            "\t".join(
                (
                    chr(code_point),
                    f"U+{code_point:04X}",
                    " ".join(entry.readings),
                    entry.tier,
                    "; ".join(entry.references),
                    sanitize_tsv(" | ".join(entry.details)) or "-",
                )
            )
            + "\n"
        )
    provenance = "".join(provenance_lines).encode("utf-8")

    unresolved_lines = ["character\tcode_point\treason\n"]
    unresolved_lines.extend(
        f"{chr(code_point)}\tU+{code_point:04X}\tno accepted official reading\n"
        for code_point in sorted(unresolved)
    )
    unresolved_report = "".join(unresolved_lines).encode("utf-8")

    conflict_lines = ["character\tcode_point\tkMandarin17\tCNS11643\tpolicy\n"]
    for code_point in sorted(radical_unihan & base.keys() & cns.readings.keys()):
        base_values = base[code_point]
        cns_values = cns.readings[code_point]
        if frozenset(base_values) == frozenset(cns_values):
            continue
        conflict_lines.append(
            f"{chr(code_point)}\tU+{code_point:04X}\t{' '.join(base_values)}\t"
            f"{' '.join(cns_values)}\tkMandarin17 retained\n"
        )
    conflicts_report = "".join(conflict_lines).encode("utf-8")

    return GeneratedFiles(dictionary, provenance, unresolved_report, conflicts_report, metrics)


def write_or_check(path: Path, rendered: bytes, check: bool) -> None:
    if check:
        try:
            committed = path.read_bytes()
        except OSError as error:
            raise ValueError(f"cannot read {path}: {error}") from error
        if committed != rendered:
            raise ValueError(f"{path} is not byte-for-byte reproducible")
    else:
        path.write_bytes(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unihan-zip", type=Path)
    parser.add_argument("--cns-properties-zip", type=Path)
    parser.add_argument("--cns-mappings-zip", type=Path)
    parser.add_argument("--radical-dictionary", type=Path, default=DEFAULT_RADICAL_DICTIONARY)
    parser.add_argument("--base-dictionary", type=Path, default=DEFAULT_BASE_DICTIONARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provenance-output", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--unresolved-output", type=Path, default=DEFAULT_UNRESOLVED)
    parser.add_argument("--conflicts-output", type=Path, default=DEFAULT_CONFLICTS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        unihan_source = read_checked_source(
            args.unihan_zip, UNIHAN_URL, UNIHAN_SHA256, "Unicode Unihan.zip"
        )
        cns_properties_source = read_checked_source(
            args.cns_properties_zip,
            CNS_PROPERTIES_URL,
            CNS_PROPERTIES_SHA256,
            "CNS Properties.zip",
        )
        cns_mappings_source = read_checked_source(
            args.cns_mappings_zip,
            CNS_MAPPINGS_URL,
            CNS_MAPPINGS_SHA256,
            "CNS MapingTables.zip",
        )
        unihan = parse_unihan(unihan_source)
        base, direct, direct_sources = build_unihan_readings(unihan)
        committed_base = parse_rime_readings(args.base_dictionary)
        if committed_base != base:
            raise ValueError(
                f"{args.base_dictionary} does not match pinned Unicode {UNICODE_VERSION} kMandarin"
            )
        generated = render_files(
            parse_rime_dictionary_scalars(args.radical_dictionary),
            unihan,
            base,
            direct,
            direct_sources,
            parse_cns(cns_properties_source, cns_mappings_source),
        )
        outputs = (
            (args.output, generated.dictionary),
            (args.provenance_output, generated.provenance),
            (args.unresolved_output, generated.unresolved),
            (args.conflicts_output, generated.conflicts),
        )
        for path, rendered in outputs:
            write_or_check(path, rendered, args.check)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    action = "verified" if args.check else "wrote"
    print(
        f"{action} {args.output}: {generated.metrics['supplement_characters']} characters, "
        f"{generated.metrics['supplement_rows']} rows, "
        f"sha256={sha256(generated.dictionary)}"
    )
    print(
        f"coverage: {generated.metrics['total_covered']}/"
        f"{generated.metrics['radical_unihan']} "
        f"({generated.metrics['total_covered'] / generated.metrics['radical_unihan']:.2%}); "
        f"unresolved={generated.metrics['unresolved']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
