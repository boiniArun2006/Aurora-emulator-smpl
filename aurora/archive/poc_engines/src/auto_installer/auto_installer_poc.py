#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7 PoC: Auto-Installer Framework
=========================================================

Creates a realistic fake game directory with multiple .exe files, then runs
the auto-installer to detect the main game .exe + find required redistributables.

Simulates a typical non-Steam game download (e.g., GOG or direct download):
- Main game .exe (with fake PE header)
- Launcher .exe (should be excluded)
- Setup .exe (should be excluded)
- VC++ redist installer (should be detected)
- DirectX installer (should be detected)
- PhysX installer (should be detected)
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from auto_installer.auto_installer import AutoInstaller
from auto_installer.exe_detector import ExeDetector
from auto_installer.pe_parser import parse_pe_file
from auto_installer.marker_utils import list_markers


# =============================================================================
# Fake PE file generator (for PoC testing)
# =============================================================================

def create_fake_pe_exe(path: Path, subsystem: int = 2, is_64_bit: bool = False,
                       product_name: str = "", file_description: str = "",
                       size_padding: int = 0) -> None:
    """Create a minimal valid PE file with optional version resource strings.
    
    subsystem: 2=GUI (game), 3=console (installer/tool)
    size_padding: extra bytes to simulate file size
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Minimal PE structure:
    # DOS Header (64 bytes) + PE Signature (4) + COFF Header (20) + Optional Header (varies)
    machine = 0x8664 if is_64_bit else 0x014c  # x64 or x86
    opt_magic = 0x20b if is_64_bit else 0x10b  # PE32+ or PE32
    
    # Build version resource strings (UTF-16LE, null-terminated, padded)
    version_data = b""
    if product_name:
        version_data += b"ProductName\x00\x00" + product_name.encode("utf-16-le") + b"\x00\x00"
    if file_description:
        version_data += b"FileDescription\x00\x00" + file_description.encode("utf-16-le") + b"\x00\x00"
    
    # DOS Header
    dos_header = bytearray(64)
    dos_header[0:2] = b"MZ"  # e_magic
    # e_lfanew at offset 60 (points to PE signature, right after DOS header)
    struct.pack_into("<I", dos_header, 60, 64)
    
    # PE Signature
    pe_sig = b"PE\x00\x00"
    
    # COFF Header (20 bytes)
    coff_header = struct.pack("<HHIIIHH",
        machine,       # Machine
        1,             # NumberOfSections
        0,             # TimeDateStamp
        0,             # PointerToSymbolTable
        0,             # NumberOfSymbols
        224 if is_64_bit else 224,  # SizeOfOptionalHeader
        0,             # Characteristics
    )
    
    # Optional Header (simplified, 224 bytes for both PE32 and PE32+)
    opt_header = bytearray(224)
    struct.pack_into("<H", opt_header, 0, opt_magic)  # Magic
    # SizeOfImage at offset 56 (PE32) or 56 (PE32+)
    struct.pack_into("<I", opt_header, 56, 0x100000)  # 1MB image size
    # Subsystem at offset 68
    struct.pack_into("<H", opt_header, 68, subsystem)
    
    # Combine
    data = bytes(dos_header) + pe_sig + coff_header + bytes(opt_header) + version_data
    
    # Pad to simulate file size
    if size_padding > 0:
        data += b"\x00" * size_padding
    
    path.write_bytes(data)


def create_fake_game_directory(game_dir: Path) -> None:
    """Create a realistic fake game directory structure for testing.
    
    Mimics a typical GOG/direct-download game:
    - Main game exe (large, GUI, with product name)
    - Launcher exe (small, GUI, "Launcher" in name)
    - Setup exe (console, "Setup" in name)
    - Uninstall exe (console)
    - VC++ redist installer
    - DirectX installer
    - PhysX installer
    """
    if game_dir.exists():
        import shutil
        shutil.rmtree(game_dir)
    game_dir.mkdir(parents=True)
    
    # Main game exe (large GUI app with product name)
    create_fake_pe_exe(
        game_dir / "Witcher3.exe",
        subsystem=2,  # GUI
        is_64_bit=True,
        product_name="The Witcher 3: Wild Hunt",
        file_description="The Witcher 3: Wild Hunt",
        size_padding=20 * 1024 * 1024,  # 20MB
    )
    
    # Launcher (should be excluded by name)
    create_fake_pe_exe(
        game_dir / "Launcher.exe",
        subsystem=2,
        product_name="Witcher 3 Launcher",
        size_padding=2 * 1024 * 1024,
    )
    
    # Setup (should be excluded by name + console subsystem)
    create_fake_pe_exe(
        game_dir / "Setup.exe",
        subsystem=3,  # console
        file_description="Setup",
        size_padding=5 * 1024 * 1024,
    )
    
    # Uninstall (should be excluded by name)
    create_fake_pe_exe(
        game_dir / "unins000.exe",
        subsystem=3,
        file_description="Uninstaller",
        size_padding=1 * 1024 * 1024,
    )
    
    # _CommonRedist/ with VC++ installers
    create_fake_pe_exe(
        game_dir / "_CommonRedist" / "vcredist" / "2013" / "vcredist_x64.exe",
        subsystem=3,
        file_description="VC++ 2013 x64 Redist",
        size_padding=5 * 1024 * 1024,
    )
    create_fake_pe_exe(
        game_dir / "_CommonRedist" / "MSVC2017" / "VC_redist.x86.exe",
        subsystem=3,
        file_description="VC++ 2017 x86 Redist",
        size_padding=15 * 1024 * 1024,
    )
    
    # DirectX installer
    create_fake_pe_exe(
        game_dir / "_CommonRedist" / "DirectX" / "Jun2010" / "DXSETUP.exe",
        subsystem=3,
        file_description="DirectX Setup",
        size_padding=500 * 1024,
    )
    
    # PhysX installer (MSI - we just create a dummy file)
    physx_path = game_dir / "_CommonRedist" / "PhysX" / "PhysX_9.16.0318_SystemSoftware.msi"
    physx_path.parent.mkdir(parents=True, exist_ok=True)
    physx_path.write_bytes(b"FAKE_MSI_DATA")
    
    # GOG manifest (names the exe)
    gog_manifest = game_dir / "goggame-1430749937.info"
    gog_manifest.write_text(json.dumps({
        "gameId": "1430749937",
        "name": "The Witcher 3: Wild Hunt",
        "playTasks": [
            {
                "category": "game",
                "name": "Play",
                "path": "Witcher3.exe",
                "arguments": ""
            }
        ]
    }, indent=2), encoding="utf-8")


# =============================================================================
# PoC test
# =============================================================================

def run_poc(output_dir: Path):
    print("=== Aurora Emulator - Phase 7 PoC: Auto-Installer Framework ===\n")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    game_dir = output_dir / "fake_game"
    
    # ---- Step 1: Create fake game directory ----
    print("[1/4] Creating fake game directory (mimics GOG download) ...")
    create_fake_game_directory(game_dir)
    
    # List what we created
    exes = list(game_dir.glob("*.exe"))
    print(f"      Game directory: {game_dir}")
    print(f"      Root .exe files: {len(exes)}")
    for exe in exes:
        print(f"        - {exe.name} ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"      _CommonRedist/ has VC++, DirectX, PhysX installers")
    print(f"      GOG manifest: goggame-1430749937.info")
    print()
    
    # ---- Step 2: Test PE parser ----
    print("[2/4] Testing PE header parser ...")
    for exe in exes:
        pe_info = parse_pe_file(exe)
        print(f"      {exe.name}:")
        print(f"        Valid PE: {pe_info.is_valid_pe}, Machine: {pe_info.machine}")
        print(f"        Subsystem: {pe_info.subsystem_name}, 64-bit: {pe_info.is_64_bit}")
        print(f"        Product: {pe_info.product_name or '(none)'}")
        print(f"        Description: {pe_info.file_description or '(none)'}")
        print(f"        Likely game: {pe_info.likely_game_exe}")
    print()
    
    # ---- Step 3: Test exe detector ----
    print("[3/4] Testing main .exe detector ...")
    detector = ExeDetector()
    detection = detector.detect(game_dir)
    
    if detection.best:
        print(f"      Detected: {detection.best.path.name}")
        print(f"      Method: {detection.method}")
        print(f"      Score: {detection.best.score:.1f}")
        print(f"      Reason: {detection.best.detection_reason}")
        print(f"      Product: {detection.best.pe_info.product_name or '(none)'}")
        if detection.ambiguous:
            print(f"      WARNING: ambiguous (multiple candidates)")
            print(f"      Top 5 candidates:")
            for i, cand in enumerate(detection.candidates[:5]):
                print(f"        {i+1}. {cand.path.name} (score={cand.score:.1f}) - {cand.display_name}")
    else:
        print(f"      FAIL: could not detect main exe")
    print()
    
    # ---- Step 4: Test full auto-installer ----
    print("[4/4] Testing full auto-installer (exe detection + redistributables) ...")
    installer = AutoInstaller()
    result = installer.analyze(game_dir)
    
    print(f"\n      Main game .exe:")
    if result.game_exe:
        print(f"        Path: {result.game_exe.path.name}")
        print(f"        Detection method: {result.game_exe_detection_method}")
        print(f"        Product: {result.game_exe.display_name}")
        if result.game_exe_ambiguous:
            print(f"        Status: AMBIGUOUS (would ask user to confirm)")
        else:
            print(f"        Status: Confidently detected")
    
    print(f"\n      Redistributables found ({len(result.install_commands)}):")
    if result.install_commands:
        for cmd in result.install_commands:
            print(f"        - {cmd.description}")
            print(f"          Command: {cmd.to_wine_command()}")
    else:
        print(f"        (none found)")
    
    print(f"\n      Steps skipped ({len(result.steps_skipped)}):")
    for skip in result.steps_skipped:
        print(f"        - {skip}")
    
    # ---- Summary ----
    print(f"\n=== Summary ===")
    print(f"  Game .exe detected: {'YES' if result.game_exe else 'NO'}")
    print(f"  Detection method: {result.game_exe_detection_method}")
    print(f"  Redistributables to install: {len(result.install_commands)}")
    print(f"  Combined Wine command:")
    if result.install_commands:
        batch = result.to_wine_batch_command()
        # Truncate for display
        print(f"    {batch[:200]}{'...' if len(batch) > 200 else ''}")
    print()
    print(f"  NOTE: In production, the Phase 5 orchestrator would:")
    print(f"    1. Run this auto-installer on game install")
    print(f"    2. Execute the Wine batch command (silent installs)")
    print(f"    3. Write marker files so it doesn't reinstall")
    print(f"    4. Run AOT preprocessing (Phases 1-4)")
    print(f"    5. Launch the detected game .exe via Box64 + Wine")
    
    # Save results
    result_json = {
        "game_exe": {
            "path": str(result.game_exe.path) if result.game_exe else None,
            "name": result.game_exe.path.name if result.game_exe else None,
            "product": result.game_exe.display_name if result.game_exe else None,
            "detection_method": result.game_exe_detection_method,
            "ambiguous": result.game_exe_ambiguous,
        },
        "install_commands": [
            {
                "description": cmd.description,
                "executable": cmd.executable,
                "args": cmd.args,
            }
            for cmd in result.install_commands
        ],
        "steps_skipped": result.steps_skipped,
        "combined_wine_command": result.to_wine_batch_command(),
    }
    result_path = output_dir / "auto_installer_results.json"
    result_path.write_text(json.dumps(result_json, indent=2))
    print(f"\nResults JSON: {result_path}")


def main():
    parser = argparse.ArgumentParser(description="Aurora Emulator - Phase 7 Auto-Installer PoC")
    parser.add_argument("--output_dir", type=Path,
                        default=PROJECT_ROOT / "tests" / "auto_installer_output")
    args = parser.parse_args()
    run_poc(args.output_dir)


if __name__ == "__main__":
    main()
