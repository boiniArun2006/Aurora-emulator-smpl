#!/usr/bin/env python3
"""
Aurora Emulator - Phase 6: Mali Vulkan Sanitizer - Rule Database
=================================================================

Database of known Mali Vulkan driver bugs and the rules to work around them.
Each rule describes:
- The problematic extension or Vulkan call
- Which Mali GPU generations are affected
- The workaround (blacklist, rewrite, emulate, or warn)

Sources (all confirmed real issues):
- VK_EXT_descriptor_indexing: missing/buggy on Mali, breaks DXVK bindless
  (https://github.com/doitsujin/dxvk/issues - multiple)
- VK_EXT_fragment_density_map: crashes Mali GPUs
- VK_KHR_shader_subgroup: not usable on Android Mali drivers
- Pipeline cache: corruption causes stutter on Mali Valhall
- DEVICE_LOST: Mali reports DEVICE_LOST on valid API usage (OOM masking)
- MSAA: 100% crash on Mali-G52/G72 with Vulkan (Unreal Engine forum)

In production, this would be a C++ Vulkan layer loaded via VK_INSTANCE_LAYERS.
For PoC, we simulate the interception in Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# =============================================================================
# Enums
# =============================================================================

class MaliGeneration(Enum):
    """Mali GPU generations, ordered by age."""
    MIDGARD = "midgard"          # Mali-T6xx/T7xx (ancient, hopeless)
    BIFROST = "bifrost"          # Mali-G51/G52/G71/G72/G76
    VALHALL = "valhall"          # Mali-G57/G77/G78/G610
    VALHALL_2 = "valhall_2"     # Mali-G310/G610/G715
    IMMORTALIS = "immortalis"    # Immortalis-G720/Mali-G920 (has ray tracing)


class RuleAction(Enum):
    """What the sanitizer does when a rule matches."""
    BLACKLIST_EXTENSION = "blacklist_extension"  # Remove from enabled extensions
    REWRITE_CALL = "rewrite_call"                # Transform the call to a safe equivalent
    EMULATE_SOFTWARE = "emulate_software"        # Implement in software (slow but works)
    WARN_ONLY = "warn_only"                      # Log a warning but pass through
    BLOCK_CALL = "block_call"                    # Refuse to make the call (return error)


# =============================================================================
# Rule dataclass
# =============================================================================

@dataclass
class SanitizerRule:
    """A single sanitizer rule."""
    rule_id: str                          # unique ID for logging
    description: str                      # human-readable description
    action: RuleAction                    # what to do
    affected_generations: list[MaliGeneration]  # which Mali gens have this issue

    # What triggers the rule (one of):
    extension_name: Optional[str] = None  # e.g. "VK_EXT_descriptor_indexing"
    call_name: Optional[str] = None       # e.g. "vkCmdBindDescriptorSets"

    # For REWRITE_CALL: the replacement call (or None to just modify args)
    rewrite_to: Optional[str] = None
    rewrite_description: Optional[str] = None

    # Severity for logging
    severity: str = "warning"  # "info", "warning", "error"


# =============================================================================
# The rule database
# =============================================================================

# All known Mali issues and their workarounds.
# This is the heart of the sanitizer - it's what no competitor has.
RULES: list[SanitizerRule] = [
    # ----- Extension blacklists -----

    SanitizerRule(
        rule_id="MALI-001",
        description="VK_EXT_descriptor_indexing is buggy on Mali Valhall - causes "
                    "DEVICE_LOST when DXVK uses bindless textures",
        action=RuleAction.BLACKLIST_EXTENSION,
        affected_generations=[MaliGeneration.VALHALL, MaliGeneration.VALHALL_2],
        extension_name="VK_EXT_descriptor_indexing",
        severity="error",
    ),
    SanitizerRule(
        rule_id="MALI-002",
        description="VK_EXT_fragment_density_map crashes Mali GPUs (confirmed on G77, G610)",
        action=RuleAction.BLACKLIST_EXTENSION,
        affected_generations=[MaliGeneration.BIFROST, MaliGeneration.VALHALL,
                               MaliGeneration.VALHALL_2],
        extension_name="VK_EXT_fragment_density_map",
        severity="error",
    ),
    SanitizerRule(
        rule_id="MALI-003",
        description="VK_KHR_shader_subgroup not usable on Android Mali - subgroup ops "
                    "silently produce wrong results",
        action=RuleAction.BLACKLIST_EXTENSION,
        affected_generations=[MaliGeneration.BIFROST, MaliGeneration.VALHALL,
                               MaliGeneration.VALHALL_2],
        extension_name="VK_KHR_shader_subgroup",
        severity="error",
    ),
    SanitizerRule(
        rule_id="MALI-004",
        description="VK_EXT_graphics_pipeline_library is unstable on Mali - pipeline "
                    "linking produces broken pipelines",
        action=RuleAction.BLACKLIST_EXTENSION,
        affected_generations=[MaliGeneration.VALHALL],
        extension_name="VK_EXT_graphics_pipeline_library",
        severity="warning",
    ),

    # ----- Call rewrites -----

    SanitizerRule(
        rule_id="MALI-005",
        description="vkCmdBindDescriptorSets with >4 descriptor sets crashes Mali - "
                    "Mali driver has a hard limit of 4 bound descriptor sets",
        action=RuleAction.REWRITE_CALL,
        affected_generations=[MaliGeneration.VALHALL, MaliGeneration.VALHALL_2],
        call_name="vkCmdBindDescriptorSets",
        rewrite_to="vkCmdBindDescriptorSets_split",
        rewrite_description="Split into multiple calls, 4 sets per call",
        severity="warning",
    ),
    SanitizerRule(
        rule_id="MALI-006",
        description="vkAllocateDescriptorSets with large descriptor counts causes "
                    "OOM -> DEVICE_LOST on Mali (Mali masks OOM as DEVICE_LOST)",
        action=RuleAction.REWRITE_CALL,
        affected_generations=[MaliGeneration.VALHALL, MaliGeneration.VALHALL_2],
        call_name="vkAllocateDescriptorSets",
        rewrite_to="vkAllocateDescriptorSets_chunked",
        rewrite_description="Allocate in chunks of 1024 descriptors max",
        severity="warning",
    ),
    SanitizerRule(
        rule_id="MALI-007",
        description="vkCreateComputePipelines with subgroup ops produces wrong results "
                    "on Mali - rewrite to use workgroup shared memory instead",
        action=RuleAction.REWRITE_CALL,
        affected_generations=[MaliGeneration.VALHALL, MaliGeneration.VALHALL_2],
        call_name="vkCreateComputePipelines",
        rewrite_to="vkCreateComputePipelines_no_subgroups",
        rewrite_description="Recompile SPIR-V to replace subgroup ops with shared memory",
        severity="warning",
    ),

    # ----- MSAA crash -----

    SanitizerRule(
        rule_id="MALI-008",
        description="MSAA (rasterizationSamples > 1) causes 100% crash on Mali-G52/G72 "
                    "with Vulkan (confirmed Unreal Engine forum)",
        action=RuleAction.BLOCK_CALL,
        affected_generations=[MaliGeneration.BIFROST],
        call_name="vkCmdDrawIndexed_MSAA",
        severity="error",
    ),

    # ----- Pipeline cache -----

    SanitizerRule(
        rule_id="MALI-009",
        description="Mali pipeline cache is unreliable on Valhall - corrupted caches "
                    "cause stutter. Aurora's Phase 4 cloud cache replaces this.",
        action=RuleAction.WARN_ONLY,
        affected_generations=[MaliGeneration.VALHALL],
        call_name="vkCreatePipelineCache",
        severity="info",
    ),

    # ----- Memory allocation -----

    SanitizerRule(
        rule_id="MALI-010",
        description="Mali reports DEVICE_LOST on valid vkAllocateMemory calls when "
                    "memory is fragmented. Rewrite to use suballocation.",
        action=RuleAction.REWRITE_CALL,
        affected_generations=[MaliGeneration.VALHALL, MaliGeneration.VALHALL_2],
        call_name="vkAllocateMemory",
        rewrite_to="vkAllocateMemory_suballocated",
        rewrite_description="Use a suballocator (VMA-style) to avoid fragmentation",
        severity="warning",
    ),
]


def get_rules_for_generation(gen: MaliGeneration) -> list[SanitizerRule]:
    """Get all rules that apply to a specific Mali generation."""
    return [r for r in RULES if gen in r.affected_generations]


def get_rules_for_extension(ext_name: str, gen: MaliGeneration) -> list[SanitizerRule]:
    """Get all rules that match a specific extension on a specific generation."""
    return [r for r in RULES
            if r.extension_name == ext_name and gen in r.affected_generations]


def get_rules_for_call(call_name: str, gen: MaliGeneration) -> list[SanitizerRule]:
    """Get all rules that match a specific Vulkan call on a specific generation."""
    return [r for r in RULES
            if r.call_name == call_name and gen in r.affected_generations]


def rule_summary() -> dict:
    """Return a summary of the rule database."""
    by_action = {}
    by_gen = {}
    for r in RULES:
        by_action[r.action.value] = by_action.get(r.action.value, 0) + 1
        for g in r.affected_generations:
            by_gen[g.value] = by_gen.get(g.value, 0) + 1
    return {
        "total_rules": len(RULES),
        "by_action": by_action,
        "by_generation": by_gen,
    }
