#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: Box64 Launcher Component (stub)
===========================================================

STUB for Phase 7. In Phase 7, this will:
- Extract the bundled Box64 binary to imagefs/usr/local/bin/box64
- Write config.box64rc with per-game settings
- Launch Box64 with the env var matrix + game executable
- Track PID for pause/resume/stop

For Phase 5 PoC, we just print what we WOULD do.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import EnvironmentComponent


class Box64LauncherComponent(EnvironmentComponent):
    """Phase 7 component: launches the game via Box64. STUB for now."""

    def __init__(self, guest_executable: str = "",
                 working_dir: Optional[Path] = None):
        super().__init__(name="Box64Launcher")
        self.guest_executable = guest_executable
        self.working_dir = working_dir
        self.pid: int = -1

    def start(self) -> None:
        super().start()
        if not self.guest_executable:
            print(f"  [Box64Launcher] No guest executable, skipping launch (PoC stub)")
            return
        print(f"  [Box64Launcher] Would launch: box64 {self.guest_executable}")
        print(f"  [Box64Launcher] Working dir: {self.working_dir}")
        print(f"  [Box64Launcher] (Phase 7 will actually exec the process)")
        self.pid = -1  # No real PID in stub

    def stop(self) -> None:
        if self.pid != -1:
            print(f"  [Box64Launcher] Would kill process {self.pid}")
        super().stop()

    def pause(self) -> None:
        super().pause()
        if self.pid != -1:
            print(f"  [Box64Launcher] Would SIGSTOP process {self.pid}")

    def resume(self) -> None:
        super().resume()
        if self.pid != -1:
            print(f"  [Box64Launcher] Would SIGCONT process {self.pid}")
