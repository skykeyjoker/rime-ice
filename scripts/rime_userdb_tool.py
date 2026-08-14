#!/usr/bin/env python3
"""List, export, or import Rime user dictionaries through an installed rime.dll.

The tool uses librime's public levers API and never renames or edits LevelDB
files directly. Stop the Rime frontend before using export or import so the
user database is not open in another process.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys


class RimeTraits(ctypes.Structure):
    _fields_ = [
        ("data_size", ctypes.c_int),
        ("shared_data_dir", ctypes.c_char_p),
        ("user_data_dir", ctypes.c_char_p),
        ("distribution_name", ctypes.c_char_p),
        ("distribution_code_name", ctypes.c_char_p),
        ("distribution_version", ctypes.c_char_p),
        ("app_name", ctypes.c_char_p),
        ("modules", ctypes.POINTER(ctypes.c_char_p)),
        ("min_log_level", ctypes.c_int),
        ("log_dir", ctypes.c_char_p),
        ("prebuilt_data_dir", ctypes.c_char_p),
        ("staging_dir", ctypes.c_char_p),
    ]


class RimeModule(ctypes.Structure):
    _fields_ = [
        ("data_size", ctypes.c_int),
        ("module_name", ctypes.c_char_p),
        ("initialize", ctypes.c_void_p),
        ("finalize", ctypes.c_void_p),
        ("get_api", ctypes.c_void_p),
    ]


class RimeUserDictIterator(ctypes.Structure):
    _fields_ = [("ptr", ctypes.c_void_p), ("i", ctypes.c_size_t)]


POINTER_BASE = ctypes.sizeof(ctypes.c_void_p)
POINTER_SIZE = ctypes.sizeof(ctypes.c_void_p)


def function_pointer(struct_address: int, index: int) -> int:
    """Read a function pointer from a self-versioned librime API structure."""
    address = struct_address + POINTER_BASE + index * POINTER_SIZE
    value = ctypes.c_void_p.from_address(address).value
    if not value:
        raise RuntimeError(f"Missing native function pointer at index {index}")
    return value


def encode_path(path: Path) -> bytes:
    return str(path).encode("utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_records(path: Path) -> int:
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )


class RimeLevers:
    """Minimal ctypes binding for the librime levers user-dictionary API."""

    def __init__(
        self,
        install_dir: Path,
        user_dir: Path,
        distribution_version: str,
    ) -> None:
        if os.name != "nt" or not hasattr(os, "add_dll_directory"):
            raise RuntimeError("This tool currently supports Windows Python 3.8+")

        self.install_dir = install_dir
        self.user_dir = user_dir
        rime_dll = install_dir / "rime.dll"
        if not rime_dll.is_file():
            raise FileNotFoundError(f"Installed rime.dll was not found: {rime_dll}")
        if not user_dir.is_dir():
            raise FileNotFoundError(f"Rime user directory was not found: {user_dir}")

        self._finalize = None
        self._dll_cookie = os.add_dll_directory(str(install_dir))
        self.lib = ctypes.CDLL(str(rime_dll))
        self.lib.rime_get_api.restype = ctypes.c_void_p
        self.lib.RimeFindModule.argtypes = [ctypes.c_char_p]
        self.lib.RimeFindModule.restype = ctypes.POINTER(RimeModule)

        api = self.lib.rime_get_api()
        if not api:
            raise RuntimeError("rime_get_api returned null")

        temporary_dir = Path(os.environ.get("TEMP", str(user_dir)))
        self._trait_values = {
            "shared": encode_path(install_dir / "data"),
            "user": encode_path(user_dir),
            "distribution": "小狼毫".encode("utf-8"),
            "code": b"Weasel",
            "version": distribution_version.encode("utf-8"),
            "app": b"rime.weasel.userdb_tool",
            "log": encode_path(temporary_dir / "rime.weasel"),
            "prebuilt": encode_path(install_dir / "data"),
        }
        traits = RimeTraits()
        traits.data_size = ctypes.sizeof(RimeTraits) - ctypes.sizeof(ctypes.c_int)
        traits.shared_data_dir = self._trait_values["shared"]
        traits.user_data_dir = self._trait_values["user"]
        traits.distribution_name = self._trait_values["distribution"]
        traits.distribution_code_name = self._trait_values["code"]
        traits.distribution_version = self._trait_values["version"]
        traits.app_name = self._trait_values["app"]
        traits.modules = None
        traits.min_log_level = 1
        traits.log_dir = self._trait_values["log"]
        traits.prebuilt_data_dir = self._trait_values["prebuilt"]
        traits.staging_dir = None
        self.traits = traits

        setup = ctypes.CFUNCTYPE(None, ctypes.POINTER(RimeTraits))(
            function_pointer(api, 0)
        )
        deployer_initialize = ctypes.CFUNCTYPE(
            None, ctypes.POINTER(RimeTraits)
        )(function_pointer(api, 7))
        self._finalize = ctypes.CFUNCTYPE(None)(function_pointer(api, 3))

        setup(ctypes.byref(self.traits))
        deployer_initialize(ctypes.byref(self.traits))

        module = self.lib.RimeFindModule(b"levers")
        if not module or not module.contents.get_api:
            raise RuntimeError("The installed rime.dll has no levers module API")
        get_api = ctypes.CFUNCTYPE(ctypes.c_void_p)(module.contents.get_api)
        levers_api = get_api()
        if not levers_api:
            raise RuntimeError("Rime levers API returned null")

        self._iter_init = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.POINTER(RimeUserDictIterator)
        )(function_pointer(levers_api, 24))
        self._iter_destroy = ctypes.CFUNCTYPE(
            None, ctypes.POINTER(RimeUserDictIterator)
        )(function_pointer(levers_api, 25))
        self._iter_next = ctypes.CFUNCTYPE(
            ctypes.c_char_p, ctypes.POINTER(RimeUserDictIterator)
        )(function_pointer(levers_api, 26))
        self._export = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p
        )(function_pointer(levers_api, 29))
        self._import = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p
        )(function_pointer(levers_api, 30))

    def close(self) -> None:
        if self._finalize:
            self._finalize()
            self._finalize = None
        if self._dll_cookie:
            self._dll_cookie.close()
            self._dll_cookie = None

    def list_user_dicts(self) -> list[str]:
        iterator = RimeUserDictIterator()
        if not self._iter_init(ctypes.byref(iterator)):
            raise RuntimeError("Failed to initialize the user dictionary iterator")
        names: list[str] = []
        try:
            while True:
                value = self._iter_next(ctypes.byref(iterator))
                if not value:
                    break
                names.append(value.decode("utf-8"))
        finally:
            self._iter_destroy(ctypes.byref(iterator))
        return names

    def export_text(self, name: str, text_file: Path) -> int:
        records = self._export(name.encode("utf-8"), encode_path(text_file))
        if records < 0:
            raise RuntimeError(f"Failed to export user dictionary {name}")
        if not text_file.is_file():
            raise RuntimeError(f"Export did not create the text file: {text_file}")
        return records

    def import_text(self, name: str, text_file: Path) -> int:
        records = self._import(name.encode("utf-8"), encode_path(text_file))
        if records < 0:
            raise RuntimeError(f"Failed to import user dictionary {name}")
        return records


def add_file_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dict", dest="dict_name", required=True)
    parser.add_argument("--text-file", type=Path, required=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--user-dir", type=Path, required=True)
    parser.add_argument("--distribution-version", default="unknown")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe", help="List available user dictionaries")
    export_parser = subparsers.add_parser("export", help="Export a user dictionary")
    add_file_arguments(export_parser)
    export_parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing text file"
    )
    import_parser = subparsers.add_parser("import", help="Import a user dictionary")
    add_file_arguments(import_parser)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    install_dir = args.install_dir.resolve()
    user_dir = args.user_dir.resolve()

    text_file = None
    if args.command in {"export", "import"}:
        text_file = args.text_file.resolve()
        if args.command == "export":
            if text_file.exists() and not args.force:
                raise FileExistsError(
                    f"Export target already exists; pass --force to replace it: {text_file}"
                )
            if not text_file.parent.is_dir():
                raise FileNotFoundError(
                    f"Export target directory does not exist: {text_file.parent}"
                )
        elif not text_file.is_file() or text_file.stat().st_size == 0:
            raise FileNotFoundError(f"Import text file is missing or empty: {text_file}")

    levers = RimeLevers(install_dir, user_dir, args.distribution_version)
    try:
        if args.command == "probe":
            result = {"user_dicts": levers.list_user_dicts()}
        elif args.command == "export":
            assert text_file is not None
            records = levers.export_text(args.dict_name, text_file)
            result = {
                "command": "export",
                "dict": args.dict_name,
                "records": records,
                "file_records": count_records(text_file),
                "text_file": str(text_file),
                "bytes": text_file.stat().st_size,
                "sha256": sha256(text_file),
            }
        else:
            assert text_file is not None
            result = {
                "command": "import",
                "dict": args.dict_name,
                "records": levers.import_text(args.dict_name, text_file),
                "file_records": count_records(text_file),
                "text_file": str(text_file),
                "bytes": text_file.stat().st_size,
                "sha256": sha256(text_file),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        levers.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
