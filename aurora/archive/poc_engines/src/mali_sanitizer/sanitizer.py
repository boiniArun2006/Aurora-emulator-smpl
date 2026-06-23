#!/usr/bin/env python3
"""
Aurora Emulator - Phase 6: Mali Vulkan Sanitizer Core
=======================================================

The sanitizer that sits between DXVK and the Mali Vulkan driver. It:
1. Intercepts Vulkan calls (in production: via VK_INSTANCE_LAYERS)
2. Looks up each call in the rule database
3. Applies the rule: blacklist, rewrite, emulate, warn, or block
4. Logs what was changed
5. Forwards the (possibly transformed) call to the real Mali driver

In production, this would be a C++ Vulkan layer compiled as a .so and loaded
via VK_INSTANCE_LAYERS=libaurora_mali_sanitizer.so. For PoC, we simulate
the interception in Python with a Vulkan call stream.

Architecture:
    DXVK (D3D -> Vulkan calls)
       |
       v
    Aurora Mali Sanitizer (intercepts, rewrites, filters)
       |
       v
    Mali Vulkan Driver (only sees sanitized calls)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from .rule_database import (
    SanitizerRule, RuleAction, MaliGeneration,
    get_rules_for_generation, get_rules_for_extension, get_rules_for_call,
    RULES,
)


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class VulkanCall:
    """A single Vulkan API call in the intercepted stream."""
    name: str                           # e.g. "vkCmdBindDescriptorSets"
    args: dict = field(default_factory=dict)  # call arguments
    timestamp_ms: float = 0.0           # when the call was made


@dataclass
class SanitizationResult:
    """Result of sanitizing a single Vulkan call."""
    original_call: VulkanCall
    action_taken: RuleAction
    rule_id: str = ""
    rule_description: str = ""
    rewritten_to: str = ""              # new call name (if rewritten)
    rewrite_description: str = ""
    severity: str = "info"
    time_ms: float = 0.0


@dataclass
class SanitizerStats:
    """Aggregate statistics over a sanitization session."""
    total_calls: int = 0
    calls_passed_through: int = 0       # no rule matched, passed unchanged
    calls_blacklisted: int = 0          # extension was blacklisted (call not made)
    calls_rewritten: int = 0            # call was rewritten
    calls_emulated: int = 0             # call was emulated in software
    calls_blocked: int = 0              # call was blocked (returned error)
    calls_warned: int = 0               # warning logged but call passed through
    extensions_blacklisted: list[str] = field(default_factory=list)
    rules_triggered: dict[str, int] = field(default_factory=dict)  # rule_id -> count
    total_time_ms: float = 0.0


# =============================================================================
# Mali sanitizer
# =============================================================================

class MaliSanitizer:
    """
    The sanitizer. Initialized with a Mali generation and a set of enabled
    extensions. Processes a stream of Vulkan calls and returns sanitized calls.

    Usage:
        sanitizer = MaliSanitizer(MaliGeneration.VALHALL, ["VK_EXT_descriptor_indexing", ...])
        sanitized = sanitizer.sanitize_call(VulkanCall(name="vkCmdBindDescriptorSets", ...))
    """

    def __init__(self, generation: MaliGeneration,
                 enabled_extensions: list[str]):
        if not isinstance(generation, MaliGeneration):
            raise TypeError(f"generation must be MaliGeneration, got {type(generation)}")

        self.generation = generation
        self.enabled_extensions = list(enabled_extensions)
        self.stats = SanitizerStats()

        # Apply extension blacklists at init time (before any calls)
        self._blacklisted_extensions: set[str] = set()
        self._apply_extension_blacklists()

    def _apply_extension_blacklists(self) -> None:
        """Remove blacklisted extensions from enabled_extensions."""
        rules = get_rules_for_generation(self.generation)
        for rule in rules:
            if rule.action == RuleAction.BLACKLIST_EXTENSION and rule.extension_name:
                if rule.extension_name in self.enabled_extensions:
                    self.enabled_extensions.remove(rule.extension_name)
                    self._blacklisted_extensions.add(rule.extension_name)
                    self.stats.extensions_blacklisted.append(rule.extension_name)
                    self.stats.rules_triggered[rule.rule_id] = \
                        self.stats.rules_triggered.get(rule.rule_id, 0) + 1
                    print(f"  [MaliSanitizer] BLACKLIST {rule.extension_name} "
                          f"({rule.rule_id}): {rule.description[:80]}")

    def sanitize_call(self, call: VulkanCall) -> SanitizationResult:
        """
        Sanitize a single Vulkan call. Returns a SanitizationResult describing
        what happened.
        """
        t0 = time.perf_counter()
        self.stats.total_calls += 1

        # Look up rules for this call on this generation
        rules = get_rules_for_call(call.name, self.generation)

        if not rules:
            # No rule matches - pass through unchanged
            self.stats.calls_passed_through += 1
            elapsed = (time.perf_counter() - t0) * 1000
            self.stats.total_time_ms += elapsed
            return SanitizationResult(
                original_call=call,
                action_taken=RuleAction.WARN_ONLY,  # "no action" - reuse enum
                time_ms=elapsed,
            )

        # Apply the first matching rule (rules are prioritized by order in RULES)
        rule = rules[0]
        self.stats.rules_triggered[rule.rule_id] = \
            self.stats.rules_triggered.get(rule.rule_id, 0) + 1
        elapsed = (time.perf_counter() - t0) * 1000
        self.stats.total_time_ms += elapsed

        if rule.action == RuleAction.REWRITE_CALL:
            self.stats.calls_rewritten += 1
            return SanitizationResult(
                original_call=call,
                action_taken=rule.action,
                rule_id=rule.rule_id,
                rule_description=rule.description,
                rewritten_to=rule.rewrite_to or call.name,
                rewrite_description=rule.rewrite_description or "",
                severity=rule.severity,
                time_ms=elapsed,
            )
        elif rule.action == RuleAction.EMULATE_SOFTWARE:
            self.stats.calls_emulated += 1
            return SanitizationResult(
                original_call=call,
                action_taken=rule.action,
                rule_id=rule.rule_id,
                rule_description=rule.description,
                severity=rule.severity,
                time_ms=elapsed,
            )
        elif rule.action == RuleAction.BLOCK_CALL:
            self.stats.calls_blocked += 1
            return SanitizationResult(
                original_call=call,
                action_taken=rule.action,
                rule_id=rule.rule_id,
                rule_description=rule.description,
                severity=rule.severity,
                time_ms=elapsed,
            )
        elif rule.action == RuleAction.WARN_ONLY:
            self.stats.calls_warned += 1
            return SanitizationResult(
                original_call=call,
                action_taken=rule.action,
                rule_id=rule.rule_id,
                rule_description=rule.description,
                severity=rule.severity,
                time_ms=elapsed,
            )
        else:
            # BLACKLIST_EXTENSION shouldn't match a call - defensive
            self.stats.calls_passed_through += 1
            return SanitizationResult(
                original_call=call,
                action_taken=RuleAction.WARN_ONLY,
                time_ms=elapsed,
            )

    def get_blacklisted_extensions(self) -> set[str]:
        """Return the set of extensions that were blacklisted at init."""
        return set(self._blacklisted_extensions)

    def get_sanitized_extensions(self) -> list[str]:
        """Return the extension list after blacklisting."""
        return list(self.enabled_extensions)

    def get_stats(self) -> SanitizerStats:
        return self.stats

    def summary(self) -> dict:
        return {
            "generation": self.generation.value,
            "original_extension_count": len(self.enabled_extensions) + len(self._blacklisted_extensions),
            "sanitized_extension_count": len(self.enabled_extensions),
            "blacklisted_extensions": sorted(self._blacklisted_extensions),
            "stats": asdict(self.stats),
        }
