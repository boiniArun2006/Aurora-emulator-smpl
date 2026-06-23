#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7: PreInstallStep base class
=====================================================

Base class for all pre-install steps. Each step:
1. Checks if it should run (appliesTo - typically: marker not yet present)
2. Builds a Wine command to install the dependency (buildCommand)
3. The orchestrator runs the command, then writes the marker

Ported from GameNative's PreInstallStep.kt (MIT licensed).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .marker_utils import Marker


@dataclass
class InstallCommand:
    """A command to run via Wine to install a dependency."""
    executable: str        # Windows path, e.g. "A:\\_CommonRedist\\vcredist\\2013\\vcredist_x64.exe"
    args: str              # Install arguments, e.g. "/install /passive /norestart"
    description: str = ""  # Human-readable description for logging

    def to_wine_command(self) -> str:
        """Convert to a Wine shell command string."""
        if self.args:
            return f'"{self.executable}" {self.args}'
        return f'"{self.executable}"'

    def __str__(self) -> str:
        return f"{self.executable} {self.args}".strip()


class PreInstallStep(ABC):
    """Base class for pre-install steps. Override appliesTo() and buildCommands()."""

    @property
    @abstractmethod
    def marker(self) -> Marker:
        """The marker written after this step succeeds."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for logging."""
        ...

    @abstractmethod
    def applies_to(self, game_dir: Path) -> bool:
        """Return True if this step should run (typically: marker not yet present)."""
        ...

    @abstractmethod
    def detect(self, game_dir: Path) -> list[InstallCommand]:
        """Scan game_dir for installers. Return list of InstallCommands (empty if none found)."""
        ...

    def get_description(self, commands: list[InstallCommand]) -> str:
        """Human-readable description of what will be installed."""
        if not commands:
            return f"{self.name}: nothing to install"
        names = [c.description or c.executable for c in commands]
        return f"{self.name}: will install {len(commands)} package(s): {', '.join(names)}"
