#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7b: Audio Options
============================================

Configuration for the audio engine. Mirrors GameNative's ALSAClient.Options
and PulseAudioComponent settings.

Defaults from GameNative (tuned by thousands of users):
- latencyMillis: 144 (high but stable; lower causes crackling)
- performanceMode: 1 (low-latency)
- volume: 1.0 (max)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class PerformanceMode(IntEnum):
    """Audio performance mode (matches GameNative's ALSAClient.Options)."""
    NORMAL = 0       # Balanced
    LOW_LATENCY = 1  # Prioritize low latency (may use more CPU)
    HIGH_QUALITY = 2 # Prioritize quality (may increase latency)


class AudioDriver(str):
    """Audio driver selection."""
    PULSEAUDIO = "pulseaudio"  # Default; better for modern WASAPI games
    ALSA = "alsa"               # Better for old DirectSound games
    DISABLED = "none"           # No audio (for headless testing)


@dataclass
class AudioOptions:
    """Audio configuration. Mirrors GameNative's ALSAClient.Options."""
    latency_millis: int = 144       # Buffer latency (default 144ms for stability)
    performance_mode: PerformanceMode = PerformanceMode.LOW_LATENCY
    volume: float = 1.0             # 0.0 (mute) to 1.0 (max)
    sample_rate: int = 48000        # Hz; 48000 is Android native (avoids resampling)
    channels: int = 2               # Stereo (1=mono, 2=stereo, 6=5.1 surround)
    buffer_frames: int = 256        # Frames per buffer (smaller = lower latency but more CPU)

    def to_dict(self) -> dict:
        return {
            "latency_millis": self.latency_millis,
            "performance_mode": self.performance_mode.name,
            "volume": self.volume,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "buffer_frames": self.buffer_frames,
        }


# Default audio options (from GameNative's tuned defaults)
DEFAULT_AUDIO_OPTIONS = AudioOptions()
