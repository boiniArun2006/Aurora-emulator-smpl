#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7b: Audio Driver Auto-Selection
=========================================================

Automatically picks ALSA vs PulseAudio based on the game's audio API.
This is Aurora's addition over GameNative (which defaults to PulseAudio always).

Detection method:
- Parse the game .exe's PE imports (DLL dependencies)
- If imports include wasapi.dll or xaudio2_*.dll -> PulseAudio (better WASAPI)
- If imports include only winmm.dll or dsound.dll -> ALSA (lower overhead)
- If unknown -> PulseAudio (default, more compatible)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .audio_options import AudioDriver, AudioOptions
from .alsa_client import ALSAComponent
from .pulseaudio_component import PulseAudioComponent


# =============================================================================
# PE import scanner (simplified)
# =============================================================================

# DLL names that indicate specific audio APIs
WASAPI_DLLS = {"wasapi.dll", "avrt.dll"}
XAUDIO_DLLS = {"xaudio2_7.dll", "xaudio2_8.dll", "xaudio2_9.dll", "x3daudio1_7.dll"}
DIRECTSOUND_DLLS = {"dsound.dll"}
WINMM_DLLS = {"winmm.dll", "mmsystem.dll"}


def scan_pe_imports(file_path: Path) -> set[str]:
    """
    Scan a PE file's import table and return the set of imported DLL names.
    Simplified: scans the file for DLL name strings (production would properly
    parse the import directory).
    """
    if not file_path.is_file():
        return set()

    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except OSError:
        return set()

    # Quick scan: find strings ending in .dll (case-insensitive)
    imports: set[str] = set()
    i = 0
    while i < len(data) - 4:
        # Look for ".dll" (case-insensitive ASCII)
        if (data[i] | 0x20) == ord('.') and \
           (data[i+1] | 0x20) == ord('d') and \
           (data[i+2] | 0x20) == ord('l') and \
           (data[i+3] | 0x20) == ord('l'):
            # Walk backwards to find the start of the DLL name
            start = i
            while start > 0 and (data[start-1] >= ord('A') and data[start-1] <= ord('z')) or \
                  (data[start-1] >= ord('0') and data[start-1] <= ord('9')) or \
                  data[start-1] == ord('_') or data[start-1] == ord('-'):
                start -= 1
            name = data[start:i+4].decode("ascii", errors="ignore").lower()
            if 4 <= len(name) <= 30:
                imports.add(name)
        i += 1
    return imports


# =============================================================================
# Audio driver selector
# =============================================================================

@dataclass
class DriverSelection:
    """Result of audio driver auto-selection."""
    driver: AudioDriver
    reason: str
    detected_dlls: set[str]

    def __post_init__(self):
        # Convert set to sorted list for JSON serialization
        pass


def select_audio_driver(game_exe: Optional[Path]) -> DriverSelection:
    """
    Auto-select the best audio driver for a game.

    Args:
        game_exe: Path to the game's main .exe (None = unknown, use default)

    Returns:
        DriverSelection with the chosen driver + reason
    """
    if game_exe is None or not game_exe.is_file():
        return DriverSelection(
            driver=AudioDriver.PULSEAUDIO,
            reason="No game exe provided, using default (PulseAudio)",
            detected_dlls=set(),
        )

    imports = scan_pe_imports(game_exe)

    # Check for WASAPI (modern games) -> PulseAudio
    wasapi_found = imports & WASAPI_DLLS
    if wasapi_found:
        return DriverSelection(
            driver=AudioDriver.PULSEAUDIO,
            reason=f"Game imports WASAPI ({', '.join(wasapi_found)}) - PulseAudio has better WASAPI support",
            detected_dlls=imports,
        )

    # Check for XAudio2 -> PulseAudio
    xaudio_found = imports & XAUDIO_DLLS
    if xaudio_found:
        return DriverSelection(
            driver=AudioDriver.PULSEAUDIO,
            reason=f"Game imports XAudio2 ({', '.join(xaudio_found)}) - PulseAudio recommended",
            detected_dlls=imports,
        )

    # Check for DirectSound only (old games) -> ALSA (lower overhead)
    dsound_found = imports & DIRECTSOUND_DLLS
    winmm_found = imports & WINMM_DLLS
    if (dsound_found or winmm_found) and not wasapi_found and not xaudio_found:
        api = ", ".join(dsound_found | winmm_found)
        return DriverSelection(
            driver=AudioDriver.ALSA,
            reason=f"Game uses legacy audio ({api}) - ALSA has lower overhead",
            detected_dlls=imports,
        )

    # Unknown audio API -> PulseAudio (default, more compatible)
    return DriverSelection(
        driver=AudioDriver.PULSEAUDIO,
        reason="Unknown audio API, using PulseAudio (most compatible)",
        detected_dlls=imports,
    )


def create_audio_component(
    selection: DriverSelection,
    options: AudioOptions,
    socket_path: Optional[Path] = None,
):
    """Create the appropriate audio component based on the driver selection."""
    if selection.driver == AudioDriver.PULSEAUDIO:
        return PulseAudioComponent(options, socket_path)
    elif selection.driver == AudioDriver.ALSA:
        return ALSAComponent(options, socket_path)
    else:
        raise ValueError(f"Unknown audio driver: {selection.driver}")
