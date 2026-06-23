/*
 * Aurora Mali Vulkan Sanitizer Layer
 * ==================================
 *
 * A Vulkan layer that sits between DXVK and the Mali Vulkan driver.
 * Intercepts Vulkan calls and applies workarounds for known Mali driver bugs.
 *
 * How it works:
 * 1. Loaded via VK_INSTANCE_LAYERS env var
 * 2. Intercepts vkCreateDevice to filter out blacklisted extensions
 * 3. Intercepts vkCmdBindDescriptorSets to split >4 sets (Mali limit)
 * 4. Intercepts vkAllocateDescriptorSets to chunk large allocations
 * 5. Logs all applied rules for debugging
 *
 * Build: Needs glibc cross-compiler for arm64 (not NDK/bionic)
 *        because it runs inside the PRoot/glibc environment.
 *        Place the resulting .so in imagefs/usr/lib/
 *
 * Usage: Set these env vars before launching the game:
 *   VK_INSTANCE_LAYERS=libaurora_mali_sanitizer.so
 *   VK_LAYER_PATH=/usr/lib
 *
 * License: MIT (Aurora Emulator)
 */

#include <vulkan/vulkan.h>
#include <android/log.h>
#include <string.h>
#include <stdlib.h>
#include <vector>
#include <string>

#define TAG "AuroraMaliSanitizer"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

// =============================================================================
// Rule database (from Phase 6 Python PoC)
// =============================================================================

// Extensions that crash or produce wrong results on Mali
static const char* BLACKLISTED_EXTENSIONS[] = {
    "VK_EXT_descriptor_indexing",        // MALI-001: causes DEVICE_LOST
    "VK_EXT_fragment_density_map",       // MALI-002: crashes Mali GPUs
    "VK_KHR_shader_subgroup",            // MALI-003: wrong results
    "VK_EXT_graphics_pipeline_library",  // MALI-004: broken pipelines on Valhall
};
static const int BLACKLISTED_EXTENSION_COUNT = 4;

// Max descriptor sets per vkCmdBindDescriptorSets call (Mali driver limit)
static const uint32_t MAX_DESCRIPTOR_SETS_PER_CALL = 4;

// Max descriptors per vkAllocateDescriptorSets call (avoid OOM -> DEVICE_LOST)
static const uint32_t MAX_DESCRIPTORS_PER_ALLOC = 1024;

// =============================================================================
// Dispatch table — pointers to the next layer's functions
// =============================================================================

// Instance-level functions
static PFN_vkGetInstanceProcAddr next_vkGetInstanceProcAddr = nullptr;
static PFN_vkCreateInstance next_vkCreateInstance = nullptr;
static PFN_vkCreateDevice next_vkCreateDevice = nullptr;
static PFN_vkDestroyInstance next_vkDestroyInstance = nullptr;
static PFN_vkEnumerateDeviceExtensionProperties next_vkEnumerateDeviceExtensionProperties = nullptr;

// Device-level functions
static PFN_vkGetDeviceProcAddr next_vkGetDeviceProcAddr = nullptr;
static PFN_vkCmdBindDescriptorSets next_vkCmdBindDescriptorSets = nullptr;
static PFN_vkAllocateDescriptorSets next_vkAllocateDescriptorSets = nullptr;
static PFN_vkDestroyDevice next_vkDestroyDevice = nullptr;

// Track stats
static int stats_extensions_blacklisted = 0;
static int stats_descriptor_sets_split = 0;
static int stats_descriptor_allocs_chunked = 0;

// =============================================================================
// Intercepted functions
// =============================================================================

// ---- MALI-001/002/003/004: Filter blacklisted extensions at device creation ----
VKAPI_ATTR VkResult VKAPI_CALL aurora_vkCreateDevice(
    VkPhysicalDevice physicalDevice,
    const VkDeviceCreateInfo* pCreateInfo,
    const VkAllocationCallbacks* pAllocator,
    VkDevice* pDevice)
{
    if (pCreateInfo == nullptr || pCreateInfo->enabledExtensionCount == 0) {
        return next_vkCreateDevice(physicalDevice, pCreateInfo, pAllocator, pDevice);
    }

    // Check which extensions to filter
    std::vector<const char*> filteredExts;
    int filteredCount = 0;

    for (uint32_t i = 0; i < pCreateInfo->enabledExtensionCount; i++) {
        const char* ext = pCreateInfo->ppEnabledExtensionNames[i];
        bool blacklisted = false;

        for (int j = 0; j < BLACKLISTED_EXTENSION_COUNT; j++) {
            if (strcmp(ext, BLACKLISTED_EXTENSIONS[j]) == 0) {
                LOGI("BLACKLIST extension: %s", ext);
                blacklisted = true;
                filteredCount++;
                stats_extensions_blacklisted++;
                break;
            }
        }

        if (!blacklisted) {
            filteredExts.push_back(ext);
        }
    }

    if (filteredCount == 0) {
        // No extensions filtered — pass through unchanged
        return next_vkCreateDevice(physicalDevice, pCreateInfo, pAllocator, pDevice);
    }

    LOGI("Filtered %d/%d extensions", filteredCount, pCreateInfo->enabledExtensionCount);

    // Create modified VkDeviceCreateInfo with filtered extensions
    VkDeviceCreateInfo modifiedInfo = *pCreateInfo;
    modifiedInfo.enabledExtensionCount = (uint32_t)filteredExts.size();
    modifiedInfo.ppEnabledExtensionNames = filteredExts.data();

    return next_vkCreateDevice(physicalDevice, &modifiedInfo, pAllocator, pDevice);
}

// ---- MALI-005: Split >4 descriptor sets (Mali crashes on >4) ----
VKAPI_ATTR void VKAPI_CALL aurora_vkCmdBindDescriptorSets(
    VkCommandBuffer commandBuffer,
    VkPipelineBindPoint pipelineBindPoint,
    VkPipelineLayout layout,
    uint32_t firstSet,
    uint32_t descriptorSetCount,
    const VkDescriptorSet* pDescriptorSets,
    uint32_t dynamicOffsetCount,
    const uint32_t* pDynamicOffsets)
{
    if (descriptorSetCount <= MAX_DESCRIPTOR_SETS_PER_CALL) {
        // Within Mali limit — pass through
        next_vkCmdBindDescriptorSets(commandBuffer, pipelineBindPoint, layout,
            firstSet, descriptorSetCount, pDescriptorSets,
            dynamicOffsetCount, pDynamicOffsets);
        return;
    }

    // Split into chunks of MAX_DESCRIPTOR_SETS_PER_CALL
    LOGI("Split vkCmdBindDescriptorSets: %u sets -> chunks of %u",
         descriptorSetCount, MAX_DESCRIPTOR_SETS_PER_CALL);
    stats_descriptor_sets_split++;

    // Note: This is a simplified split — doesn't handle dynamic offsets correctly
    // for all cases. Production version needs proper offset calculation.
    uint32_t remaining = descriptorSetCount;
    uint32_t offset = 0;
    uint32_t setOffset = firstSet;

    while (remaining > 0) {
        uint32_t chunk = (remaining > MAX_DESCRIPTOR_SETS_PER_CALL)
                       ? MAX_DESCRIPTOR_SETS_PER_CALL : remaining;

        next_vkCmdBindDescriptorSets(commandBuffer, pipelineBindPoint, layout,
            setOffset, chunk, pDescriptorSets + offset,
            0, nullptr); // Dynamic offsets not split properly (TODO)

        offset += chunk;
        setOffset += chunk;
        remaining -= chunk;
    }
}

// ---- MALI-006: Chunk large descriptor allocations (avoid OOM -> DEVICE_LOST) ----
// Note: vkAllocateDescriptorSets takes a VkDescriptorSetAllocateInfo that has
// descriptorSetCount (number of sets, not descriptors). The Mali issue is with
// the total number of descriptors across all sets. This is harder to intercept
// without inspecting the descriptor set layouts. For now, just log large allocs.
VKAPI_ATTR VkResult VKAPI_CALL aurora_vkAllocateDescriptorSets(
    VkDevice device,
    const VkDescriptorSetAllocateInfo* pAllocateInfo,
    VkDescriptorSet* pDescriptorSets)
{
    if (pAllocateInfo->descriptorSetCount > MAX_DESCRIPTORS_PER_ALLOC) {
        LOGW("Large descriptor alloc: %u sets (may cause OOM on Mali)",
             pAllocateInfo->descriptorSetCount);
        stats_descriptor_allocs_chunked++;
    }

    return next_vkAllocateDescriptorSets(device, pAllocateInfo, pDescriptorSets);
}

// =============================================================================
// Layer dispatch — vkGetInstanceProcAddr
// =============================================================================

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL aurora_vkGetDeviceProcAddr(
    VkDevice device, const char* pName);

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL aurora_vkGetInstanceProcAddr(
    VkInstance instance, const char* pName)
{
    // Intercept specific functions
    if (strcmp(pName, "vkCreateDevice") == 0) {
        return (PFN_vkVoidFunction)aurora_vkCreateDevice;
    }
    if (strcmp(pName, "vkGetInstanceProcAddr") == 0) {
        return (PFN_vkVoidFunction)aurora_vkGetInstanceProcAddr;
    }
    if (strcmp(pName, "vkGetDeviceProcAddr") == 0) {
        return (PFN_vkVoidFunction)aurora_vkGetDeviceProcAddr;
    }
    if (strcmp(pName, "vkDestroyInstance") == 0 && next_vkDestroyInstance) {
        // Log stats on instance destruction
        if (next_vkDestroyInstance) {
            LOGI("Stats: %d extensions blacklisted, %d desc set splits, %d large allocs",
                 stats_extensions_blacklisted, stats_descriptor_sets_split,
                 stats_descriptor_allocs_chunked);
        }
    }

    // Pass through to next layer
    if (next_vkGetInstanceProcAddr) {
        return next_vkGetInstanceProcAddr(instance, pName);
    }
    return nullptr;
}

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL aurora_vkGetDeviceProcAddr(
    VkDevice device, const char* pName)
{
    if (strcmp(pName, "vkCmdBindDescriptorSets") == 0) {
        return (PFN_vkVoidFunction)aurora_vkCmdBindDescriptorSets;
    }
    if (strcmp(pName, "vkAllocateDescriptorSets") == 0) {
        return (PFN_vkVoidFunction)aurora_vkAllocateDescriptorSets;
    }
    if (strcmp(pName, "vkGetDeviceProcAddr") == 0) {
        return (PFN_vkVoidFunction)aurora_vkGetDeviceProcAddr;
    }

    if (next_vkGetDeviceProcAddr) {
        return next_vkGetDeviceProcAddr(device, pName);
    }
    return nullptr;
}

// =============================================================================
// Layer initialization — called by Vulkan loader
// =============================================================================

// The Vulkan loader calls this to negotiate the layer interface version.
// We implement version 2 of the layer interface.
typedef struct {
    uint32_t sType;
    void* pNext;
    uint32_t loaderLayerInterfaceVersion;
    PFN_vkGetInstanceProcAddr pfnGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr pfnGetDeviceProcAddr;
    PFN_vkGetPhysicalDeviceProcAddr pfnGetPhysicalDeviceProcAddr;
} VkNegotiateLayerInterface;

#define VK_LUNARG_NEGOTIATE_LAYER_INTERFACE_VERSION_2 2

VKAPI_ATTR VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(
    VkNegotiateLayerInterface* pVersion)
{
    LOGI("=== Aurora Mali Sanitizer Layer Loaded ===");
    LOGI("Rules: %d blacklisted extensions, descriptor set split at %u, alloc warn at %u",
         BLACKLISTED_EXTENSION_COUNT, MAX_DESCRIPTOR_SETS_PER_CALL,
         MAX_DESCRIPTORS_PER_ALLOC);

    pVersion->loaderLayerInterfaceVersion = VK_LUNARG_NEGOTIATE_LAYER_INTERFACE_VERSION_2;
    pVersion->pfnGetInstanceProcAddr = aurora_vkGetInstanceProcAddr;
    pVersion->pfnGetDeviceProcAddr = aurora_vkGetDeviceProcAddr;
    pVersion->pfnGetPhysicalDeviceProcAddr = nullptr;

    return VK_SUCCESS;
}

// Fallback: some loaders call vkGetInstanceProcAddr with nullptr instance
// to get the negotiate function
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(
    VkInstance instance, const char* pName)
{
    if (pName && strcmp(pName, "vkNegotiateLoaderLayerInterfaceVersion") == 0) {
        return (PFN_vkVoidFunction)vkNegotiateLoaderLayerInterfaceVersion;
    }
    return aurora_vkGetInstanceProcAddr(instance, pName);
}
