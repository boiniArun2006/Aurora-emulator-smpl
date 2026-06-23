#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7: Auto-Installer Orchestrator
=========================================================

Coordinates all PreInstallSteps. For a given game directory:
1. Detect the main game .exe (via ExeDetector)
2. Run each PreInstallStep's detect() to find bundled installers
3. Return a list of Wine commands to run
4. After Wine runs them, markers are written (idempotent)

Integrates with the Phase 5 orchestrator as an EnvironmentComponent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .exe_detector import ExeDetector, DetectionResult, ExeCandidate
from .marker_utils import Marker, has_marker, add_marker, list_markers
from .pre_install_step import PreInstallStep, InstallCommand
from .steps.vcredist_step import VcRedistStep
from .steps.directx_step import DirectXStep
from .steps.physx_step import PhysXStep


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class AutoInstallResult:
    """Result of running the auto-installer on a game directory."""
    game_exe: Optional[ExeCandidate] = None
    game_exe_detection_method: str = ""
    game_exe_ambiguous: bool = False
    install_commands: list[InstallCommand] = field(default_factory=list)
    steps_skipped: list[str] = field(default_factory=list)
    markers_present: list[str] = field(default_factory=list)

    @property
    def has_installs(self) -> bool:
        return len(self.install_commands) > 0

    def to_wine_batch_command(self) -> str:
        """Combine all install commands into a single Wine shell command.
        Commands are joined with ' & ' (Windows command separator)."""
        if not self.install_commands:
            return ""
        parts = [cmd.to_wine_command() for cmd in self.install_commands]
        return " & ".join(parts)


# =============================================================================
# AutoInstaller
# =============================================================================

class AutoInstaller:
    """Coordinates exe detection + pre-install steps."""

    def __init__(self, extra_steps: list[PreInstallStep] | None = None):
        # Default steps (in order of priority)
        self.steps: list[PreInstallStep] = [
            VcRedistStep(),
            DirectXStep(),
            PhysXStep(),
        ]
        if extra_steps:
            self.steps.extend(extra_steps)

        self.exe_detector = ExeDetector()

    def analyze(self, game_dir: Path) -> AutoInstallResult:
        """
        Analyze a game directory:
        1. Detect the main game .exe
        2. Detect all required pre-install steps
        3. Return commands to run + metadata

        Does NOT execute anything — caller (orchestrator) runs the commands via Wine.
        """
        if not game_dir.is_dir():
            raise FileNotFoundError(f"Game directory not found: {game_dir}")

        result = AutoInstallResult()

        # ---- Step 1: Detect main game .exe ----
        detection = self.exe_detector.detect(game_dir)
        result.game_exe = detection.best
        result.game_exe_detection_method = detection.method
        result.game_exe_ambiguous = detection.is_ambiguous()

        # ---- Step 2: Run each PreInstallStep ----
        result.markers_present = list_markers(game_dir)

        for step in self.steps:
            if not step.applies_to(game_dir):
                result.steps_skipped.append(
                    f"{step.name} (already installed)"
                )
                continue

            commands = step.detect(game_dir)
            if commands:
                result.install_commands.extend(commands)
            else:
                result.steps_skipped.append(
                    f"{step.name} (no installer found in game dir)"
                )

        return result

    def mark_step_complete(self, game_dir: Path, step: PreInstallStep) -> None:
        """Write the marker for a completed step. Called after Wine runs the command."""
        add_marker(game_dir, step.marker)
