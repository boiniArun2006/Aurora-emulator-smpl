#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7b: PulseAudio Component
==================================================

Wraps the PulseAudio audio path. In production (Phase 8), this would:
- Start the PulseAudio server (in-userspace, libpulseaudio.so)
- Configure the AAudio sink module (PulseAudio -> Android AAudio bridge)
- Handle suspend/resume (timer-based, 120s timeout to save battery)

Ported from GameNative's PulseAudioComponent.java (MIT licensed).
Architecture:
    Wine game (WinMM/DirectSound/WASAPI)
        |
        v (Wine's PulseAudio driver)
    PulseAudio server (in-userspace, libpulseaudio.so)
        |
        v (PulseAudio's AAudio sink module - "AAudioSink")
    Android AAudio
        |
        v
    Speaker
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .audio_options import AudioOptions, PerformanceMode


SINK_NAME = "AAudioSink"  # PulseAudio sink name (matches GameNative)
SUSPEND_TIMEOUT_SECONDS = 120  # Unload module after 120s of pause (saves CPU)


@dataclass
class PulseAudioStats:
    """Runtime statistics for PulseAudio."""
    bytes_played: int = 0
    sink_reloads: int = 0           # Times the AAudio sink was reloaded
    suspend_timeouts: int = 0       # Times we hit the 120s suspend timeout
    uptime_ms: float = 0.0


class PulseAudioComponent:
    """
    PulseAudio audio component. Runs PulseAudio server in userspace.

    Suspend behavior (ported from GameNative):
    - suspend-via-thread (default): SIGSTOP the pulseaudio process
      Fast, lightweight. Resume is instant.
    - suspend-via-pactl (power-saving): pactl unload module after 120s
      Saves CPU during long pauses. Resume reloads the module.

    For PoC, we simulate the server management.
    """

    def __init__(self, options: AudioOptions,
                 socket_path: Optional[Path] = None,
                 low_latency: bool = False,
                 suspend_via_pactl: bool = False):
        self.options = options
        self.socket_path = socket_path or Path("/tmp/aurora-pulseaudio.sock")
        self.low_latency = low_latency
        self.suspend_via_pactl = suspend_via_pactl
        self.stats = PulseAudioStats()
        self._started = False
        self._paused = False
        self._start_time: float = 0.0
        self._pause_start: float = 0.0
        self._pid: int = -1  # PulseAudio process PID (production: real PID)

    @property
    def name(self) -> str:
        return "PulseAudio"

    def start(self) -> None:
        """Start the PulseAudio server + AAudio sink."""
        if self._started:
            return
        print(f"  [PulseAudio] Starting PulseAudio server")
        print(f"  [PulseAudio] Sink: {SINK_NAME}")
        print(f"  [PulseAudio] Latency: {self.options.latency_millis}ms, "
              f"mode: {self.options.performance_mode.name}")
        print(f"  [PulseAudio] Low-latency: {self.low_latency}")
        print(f"  [PulseAudio] Suspend strategy: "
              f"{'pactl' if self.suspend_via_pactl else 'thread'}")
        print(f"  [PulseAudio] (In production: would extract libpulseaudio.so + start server)")

        # In production:
        # 1. Kill any orphaned pulseaudio processes
        # 2. Start pulseaudio with:
        #    --system-msgfd=<fd>
        #    --socket-path=<socket_path>
        #    --disallow-module-loading (security)
        #    --realtime (if supported)
        # 3. Load AAudio sink module:
        #    pactl load-module module-aaudio-sink sink_name=AAudioSink
        # 4. Set volume:
        #    pactl set-sink-volume AAudioSink <volume>%

        self._started = True
        self._start_time = time.perf_counter()
        self._pid = -1  # Simulated
        print(f"  [PulseAudio] Started (simulated server, PID would be tracked)")

    def stop(self) -> None:
        """Stop the PulseAudio server."""
        if not self._started:
            return
        elapsed = (time.perf_counter() - self._start_time) * 1000
        self.stats.uptime_ms = elapsed
        print(f"  [PulseAudio] Stopping (uptime: {elapsed / 1000:.1f}s)")
        print(f"  [PulseAudio] (In production: would kill process + unload modules)")
        self._started = False
        self._paused = False
        self._pid = -1

    def pause(self) -> None:
        """Pause audio output (app going to background)."""
        if not self._started or self._paused:
            return
        self._paused = True
        self._pause_start = time.perf_counter()
        if self.suspend_via_pactl:
            # Schedule module unload after 120s
            print(f"  [PulseAudio] Paused (will unload AAudioSink in {SUSPEND_TIMEOUT_SECONDS}s)")
        else:
            # Suspend via SIGSTOP (default, fast)
            print(f"  [PulseAudio] Paused (SIGSTOP pulseaudio process)")

    def resume(self) -> None:
        """Resume audio output (app returning to foreground)."""
        if not self._started or not self._paused:
            return
        self._paused = False
        pause_duration = time.perf_counter() - self._pause_start

        if self.suspend_via_pactl and pause_duration >= SUSPEND_TIMEOUT_SECONDS:
            # Module was unloaded; need to reload
            self.stats.suspend_timeouts += 1
            self.stats.sink_reloads += 1
            print(f"  [PulseAudio] Resumed (was paused {pause_duration:.0f}s, reloading AAudioSink)")
        else:
            # Quick resume (SIGCONT or sink still loaded)
            print(f"  [PulseAudio] Resumed (was paused {pause_duration:.1f}s, instant resume)")

    def set_volume(self, volume: float) -> None:
        """Set the output volume (0.0 to 1.0)."""
        if not self._started:
            return
        self.options.volume = max(0.0, min(1.0, volume))
        pct = int(self.options.volume * 100)
        print(f"  [PulseAudio] Volume set to {pct}%")
        # In production: pactl set-sink-volume AAudioSink <pct>%

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_paused(self) -> bool:
        return self._paused
