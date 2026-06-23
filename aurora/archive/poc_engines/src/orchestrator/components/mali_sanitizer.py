#!/usr/bin/env python3
"""
Aurora Emulator - Phase 6: Mali Sanitizer Component
====================================================

Wraps Phase 6's Mali Vulkan Sanitizer as an EnvironmentComponent.
Only activates on Mali GPUs. Sets VK_INSTANCE_LAYERS to load the sanitizer
(in production) or simulates it (PoC).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT / "src"))

from mali_sanitizer.rule_database import MaliGeneration, rule_summary
from mali_sanitizer.sanitizer import MaliSanitizer, VulkanCall
from .base import EnvironmentComponent


class MaliSanitizerComponent(EnvironmentComponent):
    """Phase 6 component: Mali Vulkan sanitizer shim.

    Only activates on Mali GPUs. On non-Mali GPUs, it's a no-op.
    """

    def __init__(self, mode: str = "auto"):
        """
        Args:
            mode: "auto" (only activate on Mali), "on" (force on), "off" (force off)
        """
        super().__init__(name="MaliSanitizer")
        self.mode = mode
        self.sanitizer: MaliSanitizer | None = None
        self.active: bool = False

    def _determine_generation(self) -> MaliGeneration | None:
        """Determine the Mali generation from GPU info."""
        if not self.environment:
            return None
        gpu = self.environment.gpu_info
        if not gpu.is_mali:
            return None
        # Map GPU vendor to generation
        if gpu.vendor == "mali_valhall":
            return MaliGeneration.VALHALL
        elif gpu.vendor == "mali_immortalis":
            return MaliGeneration.IMMORTALIS
        return None

    def start(self) -> None:
        super().start()
        if not self.environment:
            print("  [MaliSanitizer] Not attached to environment")
            return

        gpu = self.environment.gpu_info
        gen = self._determine_generation()

        # Decide whether to activate
        should_activate = False
        if self.mode == "on":
            should_activate = True
        elif self.mode == "off":
            should_activate = False
        elif self.mode == "auto":
            should_activate = gen is not None  # auto-activate on Mali

        if not should_activate:
            print(f"  [MaliSanitizer] Inactive (mode={self.mode}, GPU={gpu.vendor})")
            return

        if gen is None:
            print(f"  [MaliSanitizer] Cannot activate: no Mali GPU detected (GPU={gpu.vendor})")
            return

        # In production: would set VK_INSTANCE_LAYERS=libaurora_mali_sanitizer.so
        # For PoC: just initialize the Python sanitizer
        # The extensions DXVK would request (some are problematic on Mali)
        requested_extensions = [
            "VK_EXT_descriptor_indexing",
            "VK_EXT_fragment_density_map",
            "VK_KHR_shader_subgroup",
            "VK_EXT_graphics_pipeline_library",
            "VK_KHR_swapchain",
            "VK_KHR_maintenance1",
            "VK_KHR_maintenance2",
            "VK_KHR_maintenance3",
        ]
        self.sanitizer = MaliSanitizer(gen, requested_extensions)
        self.active = True

        blacklisted = self.sanitizer.get_blacklisted_extensions()
        print(f"  [MaliSanitizer] Active (generation={gen.value})")
        print(f"  [MaliSanitizer] Blacklisted {len(blacklisted)} extensions: {sorted(blacklisted)}")
        print(f"  [MaliSanitizer] Rule database: {rule_summary()['total_rules']} rules")
        print(f"  [MaliSanitizer] (Production: would set VK_INSTANCE_LAYERS=libaurora_mali_sanitizer.so)")

    def stop(self) -> None:
        if self.active:
            stats = self.sanitizer.get_stats() if self.sanitizer else None
            if stats and stats.total_calls > 0:
                print(f"  [MaliSanitizer] Stopping. Processed {stats.total_calls} calls, "
                      f"rewrote {stats.calls_rewritten}")
        super().stop()
