#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: XEnvironment orchestrator
=====================================================

The orchestrator that holds EnvironmentComponent instances and starts/stops
them in order. Mirrors GameNative's XEnvironment.java (see
docs/REFERENCE_ARCHITECTURE.md §1).

Critical: pause/resume ordering matters.
- onPause(): suspend game process FIRST, then pause audio components
- onResume(): resume audio components FIRST, then resume game process
(audio must be ready when game wakes up, otherwise first audio call hangs)

Components are added in priority order. start() is called in add order,
stop() in reverse. For pause/resume, we use component type priorities:
- Audio components pause LAST, resume FIRST
- Game launcher components pause FIRST, resume LAST
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .aurora_imagefs import ImageFs
from .aurora_container import Container
from .aurora_gpu import GPUInfo
from .aurora_env_vars import EnvVars
from .components.base import EnvironmentComponent


class AuroraEnvironment:
    """Orchestrates environment components. Mirrors GameNative's XEnvironment."""

    def __init__(self, image_fs: ImageFs, container: Container, gpu_info: GPUInfo):
        if not image_fs.is_valid():
            raise RuntimeError(f"ImageFs is not valid: {image_fs.root_dir}")
        self.image_fs = image_fs
        self.container = container
        self.gpu_info = gpu_info
        self._components: list[EnvironmentComponent] = []
        self._started = False

    def add_component(self, component: EnvironmentComponent) -> EnvironmentComponent:
        """Add a component. Must be called before start()."""
        if self._started:
            raise RuntimeError("Cannot add components after start()")
        component.environment = self
        self._components.append(component)
        return component

    def get_component(self, component_class: type) -> Optional[EnvironmentComponent]:
        """Get the first component of the given class."""
        for c in self._components:
            if isinstance(c, component_class):
                return c
        return None

    def get_components(self, component_class: type) -> list[EnvironmentComponent]:
        """Get all components of the given class."""
        return [c for c in self._components if isinstance(c, component_class)]

    @property
    def components(self) -> list[EnvironmentComponent]:
        return list(self._components)

    def start_environment_components(self) -> None:
        """Start all components in add order."""
        if self._started:
            raise RuntimeError("Environment already started")
        # Clear tmp dir first (mirrors GameNative)
        tmp = self.image_fs.tmp_dir()
        if tmp.exists():
            for f in tmp.iterdir():
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    f.rmdir()
        # Start components in order
        for c in self._components:
            c.start()
        self._started = True

    def stop_environment_components(self) -> None:
        """Stop all components in reverse add order."""
        if not self._started:
            return
        # Stop in reverse order (last added stops first)
        for c in reversed(self._components):
            c.stop()
        self._started = False

    def on_pause(self) -> None:
        """Called when Android activity goes to background.
        Order: pause game launchers FIRST, then audio components."""
        if not self._started:
            return
        # Pause launcher components first (so the game stops making audio calls)
        from .components.box64_launcher import Box64LauncherComponent
        from .components.audio import AudioComponent
        for c in self._components:
            if isinstance(c, Box64LauncherComponent):
                c.pause()
        # Then pause audio components
        for c in self._components:
            if isinstance(c, AudioComponent):
                c.pause()
        # Then pause everything else
        for c in self._components:
            if not isinstance(c, (Box64LauncherComponent, AudioComponent)):
                c.pause()

    def on_resume(self) -> None:
        """Called when Android activity returns to foreground.
        Order: resume audio components FIRST, then game launchers.
        This is critical - audio must be ready when game wakes up."""
        if not self._started:
            return
        from .components.box64_launcher import Box64LauncherComponent
        from .components.audio import AudioComponent
        # Resume audio components first
        for c in self._components:
            if isinstance(c, AudioComponent):
                c.resume()
        # Then resume launcher components
        for c in self._components:
            if isinstance(c, Box64LauncherComponent):
                c.resume()
        # Then resume everything else
        for c in self._components:
            if not isinstance(c, (Box64LauncherComponent, AudioComponent)):
                c.resume()

    def build_env_vars(self) -> EnvVars:
        """Build the env var matrix for launching the game."""
        return EnvVars.from_defaults(self.image_fs, self.container, self.gpu_info)

    def summary(self) -> dict:
        return {
            "image_fs": self.image_fs.summary(),
            "container": self.container.summary(),
            "gpu_info": self.gpu_info.summary(),
            "components": [
                {"name": c.name, "started": c.is_started, "paused": c.is_paused}
                for c in self._components
            ],
            "started": self._started,
        }
