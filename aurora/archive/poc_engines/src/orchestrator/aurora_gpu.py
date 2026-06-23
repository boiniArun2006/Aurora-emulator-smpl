#!/usr/bin/env python3
"""
Aurora Emulator - Phase 5: GPU info detection
==============================================

Detects the GPU vendor and renderer. Used to:
- Auto-set BOX64_MMAP32=0 on Mali (workaround for Mali driver bug)
- Auto-set TU_DEBUG=noconform on Adreno/Turnip (speed hack)
- Auto-enable Phase 6 Mali sanitizer on Mali GPUs
- Pick the right Turnip driver version for Adreno 6xx/7xx/8xx

In production (Phase 8), this would call GPUInformation.java (GameNative pattern).
For PoC, we simulate with a constructor arg.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class GPUInfo:
    """Detected GPU info."""
    vendor: str          # "adreno", "mali_valhall", "mali_immortalis", "powervr", "unknown"
    renderer: str        # e.g. "Adreno (TM) 740", "Mali-G610"
    driver_version: str  # e.g. "turnip_26.0", "arm_blob_41"

    @property
    def is_adreno(self) -> bool:
        return self.vendor == "adreno"

    @property
    def is_mali(self) -> bool:
        return self.vendor in ("mali_valhall", "mali_immortalis")

    @property
    def is_powervr(self) -> bool:
        return self.vendor == "powervr"

    @classmethod
    def simulate_adreno(cls, renderer: str = "Adreno (TM) 740",
                        driver: str = "turnip_26.0") -> "GPUInfo":
        """Simulate an Adreno GPU for PoC testing."""
        return cls(vendor="adreno", renderer=renderer, driver_version=driver)

    @classmethod
    def simulate_mali(cls, renderer: str = "Mali-G610",
                      driver: str = "arm_blob_39") -> "GPUInfo":
        """Simulate a Mali Valhall GPU for PoC testing."""
        return cls(vendor="mali_valhall", renderer=renderer, driver_version=driver)

    @classmethod
    def simulate_immortalis(cls, renderer: str = "Immortalis-G720",
                            driver: str = "arm_blob_41") -> "GPUInfo":
        """Simulate a Mali Immortalis GPU for PoC testing."""
        return cls(vendor="mali_immortalis", renderer=renderer, driver_version=driver)

    def summary(self) -> dict:
        return {
            "vendor": self.vendor,
            "renderer": self.renderer,
            "driver_version": self.driver_version,
            "is_adreno": self.is_adreno,
            "is_mali": self.is_mali,
        }
