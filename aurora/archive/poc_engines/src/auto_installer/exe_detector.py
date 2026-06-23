#!/usr/bin/env python3
"""
Aurora Emulator - Phase 7: Main Game .exe Detector
====================================================

Auto-detects the main game .exe from a folder with multiple executables.
Uses a 5-tier heuristic chain:

1. Manifest files (highest confidence) — goggame-*.info, steam_appid.txt
2. Known launcher exclusion — skip setup.exe, uninstall.exe, dxsetup.exe, etc.
3. PE header analysis — GUI vs console, version info (game name vs installer name)
4. File size — main game exe is usually the largest non-installer .exe
5. Last resort — ask user (return all candidates with PE info)

Usage:
    detector = ExeDetector()
    result = detector.detect(game_dir)
    if result.is_ambiguous():
        # Show candidates to user, let them pick
        for cand in result.candidates:
            print(f"  {cand.path.name} ({cand.pe_info.product_name})")
    else:
        print(f"Auto-detected: {result.best.path}")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .pe_parser import PEInfo, parse_pe_file


# =============================================================================
# Known non-game executables to exclude (by filename, case-insensitive)
# =============================================================================
EXCLUDED_NAMES: set[str] = {
    # Installers
    "setup.exe", "install.exe", "installer.exe", "uninstall.exe", "unins000.exe",
    "unins001.exe", "remove.exe", "msiexec.exe",
    # Config tools
    "config.exe", "configuration.exe", "settings.exe", "options.exe",
    "launcher.exe", "launch.exe",  # usually a config launcher, not the game
    # Redistributable installers
    "dxsetup.exe", "dxdllreg.exe", "vcredist_x86.exe", "vcredist_x64.exe",
    "vc_redist.x86.exe", "vc_redist.x64.exe", "physx_setup.exe",
    "dotnetfx.exe", "ndp.exe", "oalinst.exe", "xnafx40_redist.msi.exe",
    # Debug/crash tools
    "crashreporter.exe", "crash_reporter.exe", "errorreporter.exe",
    "error_reporter.exe", "bugreport.exe",
    # Update/patch tools
    "updater.exe", "update.exe", "patcher.exe", "patch.exe",
    # Generic system tools
    "helper.exe", "tool.exe", "utils.exe", "tools.exe",
    # Common launcher frameworks
    "steam_api.exe", "goggame.exe",  # these are helpers, not the game
}


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class ExeCandidate:
    """A candidate main game .exe with its PE info."""
    path: Path
    pe_info: PEInfo
    file_size: int
    score: float = 0.0          # higher = more likely the main game exe
    detection_reason: str = ""  # why this candidate was scored this way

    @property
    def display_name(self) -> str:
        """Best human-readable name for this candidate."""
        if self.pe_info.product_name:
            return self.pe_info.product_name
        if self.pe_info.file_description:
            return self.pe_info.file_description
        return self.path.stem


@dataclass
class DetectionResult:
    """Result of exe detection."""
    best: Optional[ExeCandidate] = None          # highest-scoring candidate
    candidates: list[ExeCandidate] = field(default_factory=list)
    method: str = ""                              # which heuristic found it
    ambiguous: bool = False                       # True if multiple strong candidates

    def is_ambiguous(self) -> bool:
        """True if we can't confidently pick one — ask the user."""
        return self.ambiguous or self.best is None


# =============================================================================
# ExeDetector
# =============================================================================

class ExeDetector:
    """Auto-detects the main game .exe from a folder."""

    def detect(self, game_dir: Path) -> DetectionResult:
        """
        Run the full 5-tier heuristic chain.
        Returns DetectionResult with best candidate + all candidates.
        """
        if not game_dir.is_dir():
            raise FileNotFoundError(f"Game directory not found: {game_dir}")

        # ---- Tier 1: Manifest files ----
        manifest_result = self._check_manifests(game_dir)
        if manifest_result:
            return manifest_result

        # ---- Tiers 2-4: Scan all .exe files, score them ----
        candidates = self._scan_exes(game_dir)
        if not candidates:
            return DetectionResult(method="no_exes_found")

        # Score each candidate
        for cand in candidates:
            cand.score = self._score_candidate(cand)

        # Sort by score descending
        candidates.sort(key=lambda c: -c.score)

        # ---- Pick the best ----
        best = candidates[0]
        if len(candidates) > 1:
            second_best_score = candidates[1].score
            # If top 2 are within 10% of each other, it's ambiguous
            if best.score > 0 and second_best_score >= best.score * 0.9:
                return DetectionResult(
                    best=best,
                    candidates=candidates[:5],  # top 5 for user to pick from
                    method="heuristic",
                    ambiguous=True,
                )

        return DetectionResult(
            best=best,
            candidates=candidates[:5],
            method="heuristic",
        )

    def _check_manifests(self, game_dir: Path) -> Optional[DetectionResult]:
        """Tier 1: Check for GOG/Steam manifest files that name the exe."""
        # GOG: goggame-*.info files contain JSON with playTask
        gog_files = list(game_dir.glob("goggame-*.info"))
        for gog_file in gog_files:
            try:
                data = json.loads(gog_file.read_text(encoding="utf-8"))
                # GOG format: { "playTasks": [{ "arguments": "..." , "path": "..." }] }
                play_tasks = data.get("playTasks", [])
                for task in play_tasks:
                    exe_path = task.get("path", "")
                    if exe_path:
                        host_path = game_dir / exe_path
                        if host_path.is_file():
                            pe_info = parse_pe_file(host_path)
                            if pe_info.is_valid_pe:
                                return DetectionResult(
                                    best=ExeCandidate(
                                        path=host_path,
                                        pe_info=pe_info,
                                        file_size=host_path.stat().st_size,
                                        score=100.0,
                                        detection_reason=f"GOG manifest: {gog_file.name}",
                                    ),
                                    method="gog_manifest",
                                )
            except (json.JSONDecodeError, OSError):
                continue

        # Steam: steam_appid.txt (just an app ID; need to check .vdf for exe)
        steam_appid = game_dir / "steam_appid.txt"
        if steam_appid.is_file():
            # Steam install scripts (.vdf) may reference the exe
            vdf_files = list(game_dir.rglob("*.vdf"))
            for vdf in vdf_files[:5]:  # check up to 5 vdf files
                try:
                    content = vdf.read_text(encoding="utf-8", errors="ignore")
                    # Look for "Run Process" blocks with .exe paths
                    exe_match = re.search(r'"(?:Run Process|Launch)"\s*\{[^}]*"(?:exe|path|command)"\s+"([^"]+\.exe)"', content, re.IGNORECASE)
                    if exe_match:
                        exe_name = exe_match.group(1)
                        # Try to find this exe in game_dir
                        for candidate_path in game_dir.rglob(exe_name):
                            if candidate_path.is_file():
                                pe_info = parse_pe_file(candidate_path)
                                if pe_info.is_valid_pe:
                                    return DetectionResult(
                                        best=ExeCandidate(
                                            path=candidate_path,
                                            pe_info=pe_info,
                                            file_size=candidate_path.stat().st_size,
                                            score=95.0,
                                            detection_reason=f"Steam VDF: {vdf.name}",
                                        ),
                                        method="steam_vdf",
                                    )
                except OSError:
                    continue

        return None

    def _scan_exes(self, game_dir: Path) -> list[ExeCandidate]:
        """Scan game_dir for all valid PE .exe files (non-recursive for root exes)."""
        candidates: list[ExeCandidate] = []

        # First check root directory (where the main game exe usually is)
        for exe_path in sorted(game_dir.glob("*.exe")):
            pe_info = parse_pe_file(exe_path)
            if pe_info.is_valid_pe:
                candidates.append(ExeCandidate(
                    path=exe_path,
                    pe_info=pe_info,
                    file_size=exe_path.stat().st_size,
                ))

        # If no root exes, check one level deep (bin/, game/, etc.)
        if not candidates:
            for subdir in sorted(game_dir.iterdir()):
                if not subdir.is_dir():
                    continue
                for exe_path in sorted(subdir.glob("*.exe")):
                    pe_info = parse_pe_file(exe_path)
                    if pe_info.is_valid_pe:
                        candidates.append(ExeCandidate(
                            path=exe_path,
                            pe_info=pe_info,
                            file_size=exe_path.stat().st_size,
                        ))
                if candidates:
                    break  # found exes in this subdir

        return candidates

    def _score_candidate(self, cand: ExeCandidate) -> float:
        """Score a candidate. Higher = more likely the main game exe."""
        score = 0.0

        # ---- Tier 2: Exclude known non-game exes ----
        name_lower = cand.path.name.lower()
        if name_lower in EXCLUDED_NAMES:
            cand.detection_reason = f"excluded (known non-game: {cand.path.name})"
            return 0.0  # hard exclude

        # ---- Tier 3: PE header analysis ----
        # GUI app = likely game (50 points)
        if cand.pe_info.is_gui_app:
            score += 50
            cand.detection_reason = "GUI app"
        elif cand.pe_info.is_console_app:
            # Console app = likely installer/tool (penalty)
            score -= 30
            cand.detection_reason = "console app (likely installer)"

        # Has product name = likely real game (30 points)
        if cand.pe_info.product_name:
            score += 30
            cand.detection_reason += f", product: {cand.pe_info.product_name}"

        # Has file description = likely real game (10 points)
        if cand.pe_info.file_description:
            score += 10

        # ---- Tier 4: File size ----
        # Main game exe is usually large (>10MB for modern games, >1MB for old)
        size_mb = cand.file_size / (1024 * 1024)
        if size_mb > 50:
            score += 20
        elif size_mb > 10:
            score += 15
        elif size_mb > 1:
            score += 5
        elif size_mb < 0.1:  # <100KB = very small, likely a launcher/helper
            score -= 10

        # 64-bit preferred (modern games are 64-bit; installers are often 32-bit)
        if cand.pe_info.is_64_bit:
            score += 5

        return score
