#!/usr/bin/env python3
"""Generate the Rime kMandarin17 dictionary from pinned Unicode 17 data."""

from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import sys
from typing import Optional
import unicodedata
import urllib.request
import zipfile


UNICODE_VERSION = "17.0.0"
SOURCE_URL = f"https://www.unicode.org/Public/{UNICODE_VERSION}/ucd/Unihan.zip"
SOURCE_SHA256 = "f7a48b2b545acfaa77b2d607ae28747404ce02baefee16396c5d2d7a8ef34b5e"
EXPECTED_ENTRY_COUNT = 44348
EXPECTED_DICTIONARY_SHA256 = "a770bc32b15d13b05c3459642f943689fd1acd4d1c41d4c37867d409e4c8d13a"
ALLOWED_COMBINING_MARKS = {"\u0300", "\u0301", "\u0302", "\u0304", "\u0308", "\u030c"}
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPOSITORY_ROOT / "kMandarin17.dict.yaml"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_source(source_zip: Optional[Path]) -> bytes:
    if source_zip is not None:
        data = source_zip.read_bytes()
    else:
        request = urllib.request.Request(
            SOURCE_URL,
            headers={"User-Agent": "skykey-rime-ice-kMandarin17-generator"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()

    actual_hash = sha256(data)
    if actual_hash != SOURCE_SHA256:
        raise ValueError(
            f"Unicode source SHA-256 mismatch: expected {SOURCE_SHA256}, got {actual_hash}"
        )
    return data


def validate_reading(reading: str, code_point: int) -> None:
    normalized = unicodedata.normalize("NFD", reading)
    if not normalized:
        raise ValueError(f"U+{code_point:04X} has an empty kMandarin reading")
    for character in normalized:
        if "a" <= character <= "z" or character in ALLOWED_COMBINING_MARKS:
            continue
        raise ValueError(
            f"U+{code_point:04X} has an unsupported kMandarin character {character!r}"
        )


def parse_readings(source: bytes) -> list[tuple[int, str]]:
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        members = sorted(
            name
            for name in archive.namelist()
            if name.startswith("Unihan") and name.endswith(".txt")
        )
        if not members:
            raise ValueError("Unicode archive contains no Unihan*.txt members")

    readings: dict[int, str] = {}
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        for member in members:
            lines = archive.read(member).decode("utf-8").splitlines()
            for line_number, line in enumerate(lines, start=1):
                if not line or line.startswith("#"):
                    continue
                fields = line.split("\t")
                if len(fields) != 3 or fields[1] != "kMandarin":
                    continue

                code_text, _, value = fields
                if not code_text.startswith("U+"):
                    raise ValueError(f"Malformed code point at {member}:{line_number}")
                code_point = int(code_text[2:], 16)
                if code_point in readings:
                    raise ValueError(f"Duplicate kMandarin record for U+{code_point:04X}")

                # Unicode 17 defines the first value as the zh-Hans preference
                # and the second (when present) as zh-Hant. This fork is a
                # simplified-Chinese configuration, so use the first value.
                values = value.split()
                if not values:
                    raise ValueError(f"Missing kMandarin value at {member}:{line_number}")
                reading = unicodedata.normalize("NFC", values[0])
                validate_reading(reading, code_point)
                readings[code_point] = reading

    if len(readings) != EXPECTED_ENTRY_COUNT:
        raise ValueError(
            f"Unexpected kMandarin entry count: expected {EXPECTED_ENTRY_COUNT}, "
            f"got {len(readings)}"
        )
    return sorted(readings.items())


def render_dictionary(readings: list[tuple[int, str]]) -> bytes:
    header = f"""# Rime dictionary
# encoding: utf-8
#
# GENERATED FILE. DO NOT EDIT BY HAND.
# Generator: scripts/generate_kmandarin17.py
# Source: {SOURCE_URL}
# Source SHA-256: {SOURCE_SHA256}
# Policy: first kMandarin value (Unicode's zh-Hans preference)
# Entries: {len(readings)}
# Unicode data terms: https://www.unicode.org/terms_of_use.html

---
name: kMandarin17
version: \"{UNICODE_VERSION}\"
sort: original
use_preset_vocabulary: false
...

"""
    body = "".join(f"{chr(code_point)}\t{reading}\n" for code_point, reading in readings)
    return (header + body).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-zip",
        type=Path,
        help="Use a local Unicode 17 Unihan.zip (the pinned SHA-256 is still required).",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the committed dictionary is byte-for-byte reproducible.",
    )
    args = parser.parse_args()

    try:
        source = read_source(args.source_zip)
        rendered = render_dictionary(parse_readings(source))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    dictionary_hash = sha256(rendered)
    if dictionary_hash != EXPECTED_DICTIONARY_SHA256:
        print(
            "error: generated dictionary SHA-256 mismatch: "
            f"expected {EXPECTED_DICTIONARY_SHA256}, got {dictionary_hash}",
            file=sys.stderr,
        )
        return 1

    if args.check:
        try:
            committed = args.output.read_bytes()
        except OSError as error:
            print(f"error: cannot read {args.output}: {error}", file=sys.stderr)
            return 1
        if committed != rendered:
            print(
                f"error: {args.output} is not reproducible from "
                f"Unicode {UNICODE_VERSION}",
                file=sys.stderr,
            )
            return 1
        action = "verified"
    else:
        try:
            args.output.write_bytes(rendered)
        except OSError as error:
            print(f"error: cannot write {args.output}: {error}", file=sys.stderr)
            return 1
        action = "wrote"

    print(
        f"{action} {args.output} ({EXPECTED_ENTRY_COUNT} entries, "
        f"sha256={dictionary_hash})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
