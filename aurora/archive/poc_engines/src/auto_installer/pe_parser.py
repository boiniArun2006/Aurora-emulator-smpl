#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7: PE Header Parser
=============================================

Parses Windows PE (Portable Executable) files to extract:
- DOS header (validate MZ signature)
- PE signature (validate PE\0\0)
- COFF header (machine type, number of sections)
- Optional header (subsystem: GUI vs CUI, image size)
- Version resource (FileDescription, ProductName, CompanyName)

Used by exe_detector.py to:
- Confirm a file is a valid Windows .exe (not a Linux ELF or random data)
- Determine if it's a GUI app (game) or CUI app (console/installer)
- Get the game's name from the version resource

Reference: https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# PE Subsystem values (from winnt.h IMAGE_SUBSYSTEM_*)
IMAGE_SUBSYSTEM_UNKNOWN = 0
IMAGE_SUBSYSTEM_NATIVE = 1
IMAGE_SUBSYSTEM_WINDOWS_GUI = 2       # Windows GUI app (most games)
IMAGE_SUBSYSTEM_WINDOWS_CUI = 3       # Windows console app (installers, tools)
IMAGE_SUBSYSTEM_OS2_CUI = 5
IMAGE_SUBSYSTEM_POSIX_CUI = 7
IMAGE_SUBSYSTEM_WINDOWS_CE_GUI = 9
IMAGE_SUBSYSTEM_EFI_APPLICATION = 10

SUBSYSTEM_NAMES = {
    0: "unknown",
    1: "native",
    2: "gui",        # likely a game
    3: "console",    # likely an installer or tool
    5: "os2",
    7: "posix",
    9: "ce_gui",
    10: "efi",
}


@dataclass
class PEInfo:
    """Parsed PE file information."""
    is_valid_pe: bool = False
    is_64_bit: bool = False
    machine: str = ""           # "x86", "x64", "arm", "arm64", "unknown"
    subsystem: int = 0
    subsystem_name: str = ""
    image_size_bytes: int = 0
    file_description: str = ""  # from version resource
    product_name: str = ""
    company_name: str = ""
    file_version: str = ""

    @property
    def is_gui_app(self) -> bool:
        """True if this is a GUI app (likely a game, not an installer)."""
        return self.subsystem == IMAGE_SUBSYSTEM_WINDOWS_GUI

    @property
    def is_console_app(self) -> bool:
        """True if this is a console app (likely an installer or tool)."""
        return self.subsystem == IMAGE_SUBSYSTEM_WINDOWS_CUI

    @property
    def likely_game_exe(self) -> bool:
        """Heuristic: GUI app with a non-empty product name is likely a game."""
        return self.is_gui_app and bool(self.product_name)


def parse_pe_file(file_path: Path) -> PEInfo:
    """
    Parse a PE file and extract key information.
    Returns PEInfo with is_valid_pe=False if the file is not a valid PE.
    """
    info = PEInfo()
    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except OSError:
        return info

    if len(data) < 64:  # Minimum DOS header size
        return info

    # ---- DOS Header ----
    # Offset 0: e_magic (2 bytes) = "MZ" (0x5A4D)
    if data[0:2] != b"MZ":
        return info

    # Offset 60: e_lfanew (4 bytes) = offset to PE header
    e_lfanew = struct.unpack_from("<I", data, 60)[0]
    if e_lfanew + 24 > len(data):
        return info  # PE header would be past end of file

    # ---- PE Signature ----
    # At e_lfanew: signature (4 bytes) = "PE\0\0" (0x00004550)
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return info

    info.is_valid_pe = True

    # ---- COFF File Header (20 bytes, right after PE signature) ----
    coff_offset = e_lfanew + 4
    if coff_offset + 20 > len(data):
        return info

    machine, num_sections, _, _, _, opt_header_size, _ = struct.unpack_from(
        "<HHIIIHH", data, coff_offset
    )

    # Machine type
    MACHINE_TYPES = {
        0x014c: ("x86", False),
        0x8664: ("x64", True),
        0x01c0: ("arm", False),
        0xaa64: ("arm64", True),
    }
    if machine in MACHINE_TYPES:
        info.machine, info.is_64_bit = MACHINE_TYPES[machine]
    else:
        info.machine = "unknown"

    # ---- Optional Header ----
    opt_offset = coff_offset + 20
    if opt_offset + opt_header_size > len(data):
        return info

    # Optional header magic: 0x10b = PE32 (32-bit), 0x20b = PE32+ (64-bit)
    opt_magic = struct.unpack_from("<H", data, opt_offset)[0]
    if opt_magic not in (0x10b, 0x20b):
        return info

    # Subsystem is at different offsets for PE32 vs PE32+
    # PE32:  offset 68 from optional header start
    # PE32+: offset 68 from optional header start (same for subsystem)
    if opt_offset + 70 <= len(data):
        info.subsystem = struct.unpack_from("<H", data, opt_offset + 68)[0]
        info.subsystem_name = SUBSYSTEM_NAMES.get(info.subsystem, "unknown")

    # Image size (from SizeOfImage in optional header)
    # PE32:  offset 56; PE32+: offset 56 (same)
    if opt_offset + 60 <= len(data):
        info.image_size_bytes = struct.unpack_from("<I", data, opt_offset + 56)[0]

    # ---- Version Resource (simplified) ----
    # Full RT_VERSION parsing is complex (requires walking resource directory +
    # parsing VS_VERSIONINFO structure). For PoC, we do a quick string scan.
    _extract_version_strings(data, info)

    return info


def _extract_version_strings(data: bytes, info: PEInfo) -> None:
    """
    Quick-and-dirty version string extraction.
    Scans for UTF-16LE strings after known version resource markers.

    For production, we'd properly parse the RT_VERSION resource directory.
    For PoC, this catches most common cases.
    """
    # Look for UTF-16LE encoded key names followed by values
    # In PE version resources, the format is:
    #   key_name (UTF-16LE, null-terminated) + padding + value (UTF-16LE, null-terminated)
    # The key and value are separated by a null terminator + optional padding

    keys_to_find = {
        "FileDescription": "file_description",
        "ProductName": "product_name",
        "CompanyName": "company_name",
        "FileVersion": "file_version",
    }

    for key_name, attr_name in keys_to_find.items():
        # Encode key as UTF-16LE (what PE uses)
        key_bytes = key_name.encode("utf-16-le")
        search_from = 0
        while True:
            pos = data.find(key_bytes, search_from)
            if pos < 0:
                break
            search_from = pos + 1

            # Value follows the key, separated by null terminator(s)
            # Skip key bytes + null terminator (2 zero bytes) + padding
            value_start = pos + len(key_bytes)
            # Skip null bytes (UTF-16LE null = 2 zero bytes)
            # Allow up to 4 null bytes of padding
            skipped = 0
            while value_start < len(data) - 1 and data[value_start:value_start + 2] == b"\x00\x00" and skipped < 4:
                value_start += 2
                skipped += 1

            if skipped == 0:
                continue  # no separator found, skip

            # Read value as UTF-16LE until we hit a double-null
            value_end = value_start
            max_len = 512  # cap at 256 chars
            while value_end < len(data) - 1 and (value_end - value_start) < max_len:
                if data[value_end:value_end + 2] == b"\x00\x00":
                    break
                value_end += 2

            try:
                value = data[value_start:value_end].decode("utf-16-le").strip("\x00")
                # Filter: must be printable ASCII (skip garbage)
                if value and len(value) >= 2 and all(32 <= ord(c) < 127 for c in value):
                    # Reject if it looks like another key name (starts with uppercase + has no spaces)
                    # This filters out false positives where we land on a different key
                    if not (value[0].isupper() and " " not in value and value.isalpha()):
                        setattr(info, attr_name, value)
                        break  # found a good value, move to next key
            except (UnicodeDecodeError, ValueError):
                pass


def is_windows_executable(file_path: Path) -> bool:
    """Quick check: is this file a valid Windows PE executable?"""
    return parse_pe_file(file_path).is_valid_pe
