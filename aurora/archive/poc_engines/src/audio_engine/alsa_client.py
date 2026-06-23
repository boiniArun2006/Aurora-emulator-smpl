#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7b: ALSA Client
=========================================

Wraps the ALSA audio path. In production (Phase 8), this would:
- Start the ALSA server (in-userspace C code from GameNative's android_alsa/)
- Bridge ALSA PCM calls to Android AudioTrack via ALSAClient.java
- Handle audio focus (notifications don't kill audio)

For PoC, we simulate the bridge and validate the configuration.

Ported from GameNative's ALSAClient.java (MIT licensed).
Architecture:
    Wine game (WinMM/DirectSound)
        |
        v (Wine's ALSA driver)
    ALSA server (in-userspace, android_alsa/module_pcm_android_aserver.c)
        |
        v (Unix domain socket)
    ALSAClient (this module, in app process)
        |
        v
    Android AudioTrack
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


@dataclass
class ALSAClientStats:
    """Runtime statistics for the ALSA client."""
    bytes_played: int = 0
    underruns: int = 0           # Buffer underruns (cause crackling)
    audio_focus_losses: int = 0  # Times audio was interrupted by notifications
    uptime_ms: float = 0.0


class ALSAClient:
    """
    ALSA audio client. Bridges Wine's ALSA driver to Android AudioTrack.

    In production, this runs as a Unix socket server that the in-userspace
    ALSA server connects to. Audio data flows:
        Wine -> ALSA server -> Unix socket -> ALSAClient -> Android AudioTrack

    For PoC, we just simulate the bridge and track stats.
    """

    def __init__(self, options: AudioOptions, socket_path: Optional[Path] = None):
        self.options = options
        self.socket_path = socket_path or Path("/tmp/aurora-alsa.sock")
        self.stats = ALSAClientStats()
        self._running = False
        self._start_time: float = 0.0
        self._audio_track = None  # Would be Android AudioTrack in production

    def start(self) -> None:
        """Start the ALSA client (create AudioTrack, listen on socket)."""
        if self._running:
            return
        print(f"  [ALSAClient] Starting (latency={self.options.latency_millis}ms, "
              f"mode={self.options.performance_mode.name}, "
              f"rate={self.options.sample_rate}Hz, channels={self.options.channels})")
        print(f"  [ALSAClient] Socket: {self.socket_path}")

        # In production:
        # 1. Create Android AudioTrack with:
        #    - sampleRate = self.options.sample_rate
        #    - channelConfig = CHANNEL_OUT_STEREO (if channels == 2)
        #    - audioFormat = ENCODING_PCM_16BIT
        #    - bufferSizeInBytes = latency_millis * sample_rate * channels * 2 / 1000
        # 2. Start AudioTrack
        # 3. Listen on Unix socket for PCM data from the ALSA server

        self._running = True
        self._start_time = time.perf_counter()
        print(f"  [ALSAClient] Started (simulated AudioTrack)")

    def stop(self) -> None:
        """Stop the ALSA client."""
        if not self._running:
            return
        self._running = False
        elapsed = (time.perf_counter() - self._start_time) * 1000
        self.stats.uptime_ms = elapsed
        print(f"  [ALSAClient] Stopped (uptime: {elapsed / 1000:.1f}s, "
              f"bytes played: {self.stats.bytes_played:,})")

    def write_pcm(self, data: bytes) -> int:
        """Write PCM audio data. Returns bytes written.
        In production, this writes to Android AudioTrack."""
        if not self._running:
            return 0
        # Simulate playback
        self.stats.bytes_played += len(data)
        return len(data)

    def on_audio_focus_lost(self) -> None:
        """Called when Android audio focus is lost (e.g. notification)."""
        self.stats.audio_focus_losses += 1
        print(f"  [ALSAClient] Audio focus lost (count: {self.stats.audio_focus_losses})")

    def on_audio_focus_gained(self) -> None:
        """Called when Android audio focus is regained."""
        print(f"  [ALSAClient] Audio focus regained")

    def report_underrun(self) -> None:
        """Called when a buffer underrun occurs (causes crackling)."""
        self.stats.underruns += 1


class ALSAComponent:
    """
    EnvironmentComponent wrapper for the ALSA audio path.
    Manages the ALSA server (C process) + ALSAClient (Python/Java).
    """

    def __init__(self, options: AudioOptions, socket_path: Optional[Path] = None):
        self.options = options
        self.socket_path = socket_path
        self.client: Optional[ALSAClient] = None
        self._started = False
        self._paused = False

    @property
    def name(self) -> str:
        return "ALSA Audio"

    def start(self) -> None:
        if self._started:
            return
        print(f"  [ALSAComponent] Starting ALSA audio path")
        print(f"  [ALSAComponent] (In production: would extract + start android_alsa C server)")
        self.client = ALSAClient(self.options, self.socket_path)
        self.client.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        if self.client:
            self.client.stop()
        print(f"  [ALSAComponent] Stopped")
        self._started = False

    def pause(self) -> None:
        if not self._started or self._paused:
            return
        self._paused = True
        print(f"  [ALSAComponent] Paused (audio output suspended, server keeps running)")

    def resume(self) -> None:
        if not self._started or not self._paused:
            return
        self._paused = False
        print(f"  [ALSAComponent] Resumed (audio output restored)")

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_paused(self) -> bool:
        return self._paused
