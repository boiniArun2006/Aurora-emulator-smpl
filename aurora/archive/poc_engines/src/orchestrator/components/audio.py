#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: Audio Component (stub)
===================================================

STUB for Phase 7. In Phase 7, this will:
- Start ALSA server (in-userspace) for old games
- Start PulseAudio server (in-userspace) for modern games
- Set PULSE_LATENCY_MSEC env var
- Coordinate pause/resume with Box64LauncherComponent

For Phase 5 PoC, we just print what we WOULD do.
"""

from __future__ import annotations

from .base import EnvironmentComponent


class AudioComponent(EnvironmentComponent):
    """Phase 7 component: ALSA + PulseAudio audio. STUB for now."""

    def __init__(self, driver: str = "pulseaudio", latency_ms: int = 144):
        super().__init__(name="Audio")
        self.driver = driver  # "pulseaudio" or "alsa"
        self.latency_ms = latency_ms

    def start(self) -> None:
        super().start()
        print(f"  [Audio] Would start {self.driver} server (latency={self.latency_ms}ms)")
        print(f"  [Audio] (Phase 7 will actually start the audio server)")

    def stop(self) -> None:
        print(f"  [Audio] Would stop {self.driver} server")
        super().stop()

    def pause(self) -> None:
        super().pause()
        print(f"  [Audio] Paused (audio server keeps running but stops output)")

    def resume(self) -> None:
        super().resume()
        print(f"  [Audio] Resumed (audio output restored)")
