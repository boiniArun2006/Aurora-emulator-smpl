#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7c PoC: Box64 + Wine + DXVK Integration
==================================================================

Simulates the full runtime stack setup:
1. Extract Box64 binary to imagefs
2. Extract Wine to imagefs, initialize prefix
3. Extract DXVK, install DLLs to system32
4. Write per-game configs (box64rc, dxvk.conf, dll overrides)
5. Build the final launch command: box64 wine game.exe

In production (Phase 8), this is what runs when the user clicks "Launch Game".
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # aurora/ directory
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from box64_integration.box64_manager import Box64Manager, BOX64_PRESETS
from wine_integration.wine_manager import WineManager
from dxvk_integration.dxvk_manager import DXVKManager, DXVKConfig, DXVK_DLLS
from audio_engine.audio_options import AudioOptions, PerformanceMode
from audio_engine.pulseaudio_component import PulseAudioComponent


def run_poc(output_dir: Path):
    print("=== Aurora Emulator - Phase 7c PoC: Box64 + Wine + DXVK Integration ===\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    imagefs_root = output_dir / "imagefs"

    # ---- Step 1: Extract Box64 ----
    print("[1/5] Extracting Box64 ...")
    box64 = Box64Manager(imagefs_root)
    print(f"      Available versions: {[v.version for v in box64.get_available_versions()]}")
    recommended = box64.get_recommended_version()
    print(f"      Recommended: {recommended.version} ({recommended.description})")
    box64.extract(recommended.version)
    print()

    # ---- Step 2: Extract Wine + init prefix ----
    print("[2/5] Extracting Wine + initializing prefix ...")
    wine = WineManager(imagefs_root)
    print(f"      Available versions: {[v.version for v in wine.get_available_versions()]}")
    wine.extract("9.0")
    wine.init_prefix()
    print()

    # ---- Step 3: Extract DXVK + install DLLs ----
    print("[3/5] Extracting DXVK + installing DLLs ...")
    dxvk = DXVKManager(imagefs_root, wine.wineprefix)
    print(f"      Available versions: {[v.version for v in dxvk.get_available_versions()]}")
    dxvk.extract("2.6.1")
    print()

    # ---- Step 4: Write configs ----
    print("[4/5] Writing per-game configs ...")

    # Box64 rcfile with stability preset (for Witcher 3)
    preset = BOX64_PRESETS["compatibility"]
    box64.write_rcfile(preset, game_exe="/opt/witcher3/bin/witcher3.exe")

    # DXVK config (spoof as NVIDIA GTX 970 for compatibility)
    dxvk_config = DXVKConfig(
        max_device_memory=4096,
        max_feature_level="11_1",
        async_pipeline=True,
        async_shader_compile=True,
        custom_device_id="0x13C2",
        custom_vendor_id="0x10de",  # NVIDIA
        custom_device_desc="NVIDIA GeForce GTX 970",
        strict_shader_math=True,
    )
    dxvk.write_config(dxvk_config)

    # Wine DLL overrides (DXVK replaces d3d9/d3d10/d3d11/dxgi)
    dll_overrides = wine.build_dll_overrides_string(dxwrapper="dxvk")
    print(f"      WINEDLLOVERRIDES: {dll_overrides}")
    print()

    # ---- Step 5: Build the launch command ----
    print("[5/5] Building launch command ...")

    game_exe = "/opt/witcher3/bin/witcher3.exe"
    box64_cmd = box64.build_launch_command(
        game_exe=game_exe,
        preset=preset,
        extra_args=[],  # game-specific args
    )

    # The full launch command (what ProcessHelper.exec would run):
    # box64 wine /opt/witcher3/bin/witcher3.exe
    # (Wine is the first arg to Box64; Wine then launches the game)
    full_cmd = [str(box64.binary_path)] + [str(wine.wine_bin_path), game_exe]

    print(f"      Box64 binary: {box64.binary_path}")
    print(f"      Wine binary: {wine.wine_bin_path}")
    print(f"      Game exe: {game_exe}")
    print(f"      Wine prefix: {wine.wineprefix}")
    print(f"      Box64 rcfile: {box64.rcfile_path}")
    print(f"      DXVK config: {dxvk.config_path}")
    print()
    print(f"      Full launch command:")
    print(f"        {' '.join(full_cmd)}")
    print()

    # Also start audio (PulseAudio, since Witcher 3 uses WASAPI)
    print(f"      Starting audio (PulseAudio for WASAPI game) ...")
    audio = PulseAudioComponent(
        AudioOptions(latency_millis=144, performance_mode=PerformanceMode.LOW_LATENCY),
        socket_path=output_dir / "pulse.sock",
        low_latency=True,
    )
    audio.start()
    audio.pause()
    audio.resume()
    audio.stop()
    print()

    # ---- Summary ----
    print("=== Summary ===")
    print(f"  Box64: {recommended.version} (extracted to {box64.binary_path})")
    print(f"  Wine: 9.0 (extracted to {wine.wine_bin_path})")
    print(f"  DXVK: 2.6.1 (DLLs installed to {dxvk.system32})")
    print(f"  Wine prefix: {wine.wineprefix}")
    print(f"  Box64 preset: {preset.name}")
    print(f"  DXVK: spoofing NVIDIA GTX 970 for compatibility")
    print(f"  Audio: PulseAudio (WASAPI game)")
    print(f"  Launch: box64 wine {game_exe}")
    print()
    print(f"  NOTE: In production (Phase 8), the full env var matrix from Phase 5")
    print(f"  would be passed to this command (HOME, PATH, BOX64_*, DXVK_*, etc.)")
    print(f"  The Phase 5 AuroraEnvironment.build_env_vars() produces this matrix.")

    # Save results
    result = {
        "box64": {
            "version": recommended.version,
            "binary_path": str(box64.binary_path),
            "rcfile_path": str(box64.rcfile_path),
            "preset": preset.name,
        },
        "wine": {
            "version": "9.0",
            "binary_path": str(wine.wine_bin_path),
            "prefix": str(wine.wineprefix),
            "dll_overrides": dll_overrides,
        },
        "dxvk": {
            "version": "2.6.1",
            "system32": str(dxvk.system32),
            "config_path": str(dxvk.config_path),
            "config": asdict(dxvk_config),
            "installed_dlls": DXVK_DLLS,
        },
        "launch_command": full_cmd,
        "game_exe": game_exe,
    }
    result_path = output_dir / "integration_results.json"
    result_path.write_text(json.dumps(result, indent=2))
    print(f"\nResults JSON: {result_path}")


def main():
    parser = argparse.ArgumentParser(description="Aurora Phase 7c Integration PoC")
    parser.add_argument("--output_dir", type=Path,
                        default=PROJECT_ROOT / "tests" / "integration_output")
    args = parser.parse_args()
    run_poc(args.output_dir)


if __name__ == "__main__":
    main()
