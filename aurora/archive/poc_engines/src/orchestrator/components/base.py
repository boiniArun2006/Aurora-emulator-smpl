#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: EnvironmentComponent base class
===========================================================

Base class for all environment components. Mirrors GameNative's
EnvironmentComponent.java pattern (see docs/REFERENCE_ARCHITECTURE.md §1).

Components are pluggable: add only the ones you need for a particular game.
XEnvironment calls start() on each in order, and stop() in reverse order.

Lifecycle:
    start() -> [running] -> stop()
                |    ^
                v    |
              pause()/resume()

Pause/resume is used when the Android activity goes to background:
- onPause(): suspend game process FIRST, then pause audio
- onResume(): resume audio FIRST, then resume game process
(critical ordering - audio must be ready when game wakes up)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .aurora_environment import AuroraEnvironment


class EnvironmentComponent:
    """Base class for environment components. Override start/stop/pause/resume."""

    def __init__(self, name: str = ""):
        self.name: str = name or self.__class__.__name__
        self.environment: Optional["AuroraEnvironment"] = None
        self._started: bool = False
        self._paused: bool = False

    def start(self) -> None:
        """Start the component. Called by XEnvironment.start_environment_components()."""
        self._started = True
        self._paused = False

    def stop(self) -> None:
        """Stop the component. Called by XEnvironment.stop_environment_components()."""
        self._started = False
        self._paused = False

    def pause(self) -> None:
        """Pause the component (e.g. when Android activity goes to background).
        Only called if the component is started."""
        if not self._started:
            return
        self._paused = True

    def resume(self) -> None:
        """Resume the component after pause().
        Only called if the component is started and paused."""
        if not self._started:
            return
        self._paused = False

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_paused(self) -> bool:
        return self._paused

    def __repr__(self) -> str:
        state = "stopped"
        if self._started:
            state = "paused" if self._paused else "running"
        return f"<{self.name} [{state}]>"
