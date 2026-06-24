/*
 * Aurora Mali Vulkan Sanitizer Layer
 * ==================================
 *
 * A Vulkan layer that sits between DXVK and the Mali Vulkan driver.
 * Intercepts Vulkan calls and applies workarounds for known Mali driver bugs.
 *
 * Architecture:
 * This is a proper Vulkan layer that follows the Khronos layer negotiation
 * protocol. The dispatch table is populated in vkCreateInstance by walking
 * the VkLayerInstanceCreateInfo_ chain in pCreateInfo->pNext.
 *
 * Phase 6 integration into GameNative.
 *
 * License: MIT (Aurora Emulator)
 */

#include <vulkan/vulkan.h>
#include <android/log.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <vector>
#include <string>

// =============================================================================
// Vulkan layer structures — normally in vulkan/vk_layer.h, but the NDK
// doesn't ship that header. We define them here manually.
// This is standard practice for Android Vulkan layers.
// =============================================================================

// sType values for layer create info (not in NDK's vulkan_core.h)
#define VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO \
    ((VkStructureType)47)
#define VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO \
    ((VkStructureType)48)

// Layer function type enum
typedef enum VkLayerFunction {
    VK_LAYER_LINK_INFO = 0,
} VkLayerFunction;

// Instance-level layer link
typedef struct VkLayerInstanceLink_ {
    struct VkLayerInstanceLink_* pNext;
    PFN_vkGetInstanceProcAddr pfnNextGetInstanceProcAddr;
} VkLayerInstanceLink_;

// Instance-level layer create info
typedef struct {
    VkStructureType sType;
    const void* pNext;
    VkLayerFunction function;
    union {
        VkLayerInstanceLink_* pLayerInfo;
    } u;
} VkLayerInstanceCreateInfo_;

// Device-level layer link
typedef struct VkLayerDeviceLink_ {
    struct VkLayerDeviceLink_* pNext;
    PFN_vkGetInstanceProcAddr pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr pfnNextGetDeviceProcAddr;
} VkLayerDeviceLink_;

// Device-level layer create info
typedef struct {
    VkStructureType sType;
    const void* pNext;
    VkLayerFunction function;
    union {
        VkLayerDeviceLink_* pLayerInfo;
    } u;
} VkLayerDeviceCreateInfo_;

#define TAG "AuroraMaliSanitizer"
// Dual logging: try Android log (works when loaded by Android's Vulkan loader
// in bionic context), fall back to stderr (works inside glibc/PRoot context).
// This makes the layer work in BOTH environments — as a system Vulkan layer
// loaded by Android's loader, AND as a layer loaded inside PRoot's glibc env.
#define LOGI(...) do { \
    __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__); \
    fprintf(stderr, "[" TAG "] INFO: " __VA_ARGS__); fprintf(stderr, "\n"); \
} while(0)
#define LOGW(...) do { \
    __android_log_print(ANDROID_LOG_WARN, TAG, __VA_ARGS__); \
    fprintf(stderr, "[" TAG "] WARN: " __VA_ARGS__); fprintf(stderr, "\n"); \
} while(0)
#define LOGE(...) do { \
    __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__); \
    fprintf(stderr, "[" TAG "] ERROR: " __VA_ARGS__); fprintf(stderr, "\n"); \
} while(0)

// =============================================================================
// Rule database
// =============================================================================

static const char* BLACKLISTED_EXTENSIONS[] = {
    "VK_EXT_descriptor_indexing",
    "VK_EXT_fragment_density_map",
    "VK_KHR_shader_subgroup",
    "VK_EXT_graphics_pipeline_library",
};
static const int BLACKLISTED_EXTENSION_COUNT = 4;

static const uint32_t MAX_DESCRIPTOR_SETS_PER_CALL = 4;

// Stats
static int stats_extensions_blacklisted = 0;
static int stats_descriptor_sets_split = 0;

// =============================================================================
// Instance dispatch table — one per VkInstance
// =============================================================================

struct InstanceDispatch {
    PFN_vkGetInstanceProcAddr get_instance_proc_addr;
    PFN_vkCreateDevice create_device;
    PFN_vkDestroyInstance destroy_instance;
    PFN_vkEnumerateDeviceExtensionProperties enumerate_device_extensions;
};

// Map from VkInstance to its dispatch table
// (Simple linear search — there's typically only 1 instance)
static std::vector<std::pair<VkInstance, InstanceDispatch>> g_instance_dispatch;

static InstanceDispatch* get_instance_dispatch(VkInstance instance) {
    for (auto& entry : g_instance_dispatch) {
        if (entry.first == instance) return &entry.second;
    }
    return nullptr;
}

// =============================================================================
// Device dispatch table — one per VkDevice
// =============================================================================

struct DeviceDispatch {
    PFN_vkGetDeviceProcAddr get_device_proc_addr;
    PFN_vkCmdBindDescriptorSets cmd_bind_descriptor_sets;
    PFN_vkAllocateDescriptorSets allocate_descriptor_sets;
    PFN_vkDestroyDevice destroy_device;
};

static std::vector<std::pair<VkDevice, DeviceDispatch>> g_device_dispatch;

static DeviceDispatch* get_device_dispatch(VkDevice device) {
    for (auto& entry : g_device_dispatch) {
        if (entry.first == device) return &entry.second;
    }
    return nullptr;
}

// =============================================================================
// vkCreateInstance — populate the instance dispatch table
// =============================================================================

VKAPI_ATTR VkResult VKAPI_CALL aurora_vkCreateInstance(
    const VkInstanceCreateInfo* pCreateInfo,
    const VkAllocationCallbacks* pAllocator,
    VkInstance* pInstance)
{
    LOGI("=== Aurora Mali Sanitizer: vkCreateInstance intercepted ===");

    // Walk the pNext chain to find VkLayerInstanceCreateInfo_
    // This is how layers get the next layer's function pointers
    PFN_vkGetInstanceProcAddr nextGIPA = nullptr;

    const VkBaseInStructure* pChain = (const VkBaseInStructure*)pCreateInfo->pNext;
    while (pChain) {
        if (pChain->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO) {
            const VkLayerInstanceCreateInfo_* layerInfo = (const VkLayerInstanceCreateInfo_*)pChain;
            if (layerInfo->function == VK_LAYER_LINK_INFO) {
                // This is the link info — contains the next layer's vkGetInstanceProcAddr
                nextGIPA = layerInfo->u.pLayerInfo->pfnNextGetInstanceProcAddr;
                // Advance the link for the next layer in the chain
                layerInfo->u.pLayerInfo = layerInfo->u.pLayerInfo->pNext;
                break;
            }
        }
        pChain = pChain->pNext;
    }

    if (!nextGIPA) {
        LOGE("Failed to find next layer's vkGetInstanceProcAddr in pNext chain!");
        return VK_ERROR_INITIALIZATION_FAILED;
    }

    // Get the real vkCreateInstance from the next layer
    PFN_vkCreateInstance nextCreateInstance =
        (PFN_vkCreateInstance)nextGIPA(VK_NULL_HANDLE, "vkCreateInstance");
    if (!nextCreateInstance) {
        LOGE("Next layer doesn't have vkCreateInstance!");
        return VK_ERROR_INITIALIZATION_FAILED;
    }

    // Call the real vkCreateInstance
    VkResult result = nextCreateInstance(pCreateInfo, pAllocator, pInstance);
    if (result != VK_SUCCESS) {
        LOGE("Next layer's vkCreateInstance failed: %d", result);
        return result;
    }

    // Populate our dispatch table for this instance
    InstanceDispatch dispatch;
    dispatch.get_instance_proc_addr = nextGIPA;
    dispatch.create_device =
        (PFN_vkCreateDevice)nextGIPA(*pInstance, "vkCreateDevice");
    dispatch.destroy_instance =
        (PFN_vkDestroyInstance)nextGIPA(*pInstance, "vkDestroyInstance");
    dispatch.enumerate_device_extensions =
        (PFN_vkEnumerateDeviceExtensionProperties)nextGIPA(*pInstance, "vkEnumerateDeviceExtensionProperties");

    g_instance_dispatch.push_back({*pInstance, dispatch});

    LOGI("Dispatch table populated. Instance: %p", (void*)*pInstance);
    LOGI("Rules: %d blacklisted extensions, descriptor set split at %u",
         BLACKLISTED_EXTENSION_COUNT, MAX_DESCRIPTOR_SETS_PER_CALL);

    return VK_SUCCESS;
}

// =============================================================================
// vkDestroyInstance — cleanup dispatch table
// =============================================================================

VKAPI_ATTR void VKAPI_CALL aurora_vkDestroyInstance(
    VkInstance instance,
    const VkAllocationCallbacks* pAllocator)
{
    InstanceDispatch* dispatch = get_instance_dispatch(instance);
    if (dispatch && dispatch->destroy_instance) {
        dispatch->destroy_instance(instance, pAllocator);
    }

    // Remove from our table
    for (auto it = g_instance_dispatch.begin(); it != g_instance_dispatch.end(); ++it) {
        if (it->first == instance) {
            g_instance_dispatch.erase(it);
            break;
        }
    }

    LOGI("Stats: %d extensions blacklisted, %d desc set splits",
         stats_extensions_blacklisted, stats_descriptor_sets_split);
}

// =============================================================================
// vkCreateDevice — filter blacklisted extensions + populate device dispatch
// =============================================================================

VKAPI_ATTR VkResult VKAPI_CALL aurora_vkCreateDevice(
    VkPhysicalDevice physicalDevice,
    const VkDeviceCreateInfo* pCreateInfo,
    const VkAllocationCallbacks* pAllocator,
    VkDevice* pDevice)
{
    // Find the instance that owns this physical device
    // (We need the instance dispatch to get the next layer's functions)
    // Since we typically have only one instance, use the first one.
    InstanceDispatch* instDispatch = nullptr;
    if (!g_instance_dispatch.empty()) {
        instDispatch = &g_instance_dispatch[0].second;
    }

    if (!instDispatch || !instDispatch->create_device) {
        LOGE("No instance dispatch available for vkCreateDevice!");
        return VK_ERROR_INITIALIZATION_FAILED;
    }

    // Walk pNext chain to find VkLayerDeviceCreateInfo_ (for device-level linking)
    PFN_vkGetDeviceProcAddr nextGDPA = nullptr;

    const VkBaseInStructure* pChain = (const VkBaseInStructure*)pCreateInfo->pNext;
    while (pChain) {
        if (pChain->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO) {
            const VkLayerDeviceCreateInfo_* layerInfo = (const VkLayerDeviceCreateInfo_*)pChain;
            if (layerInfo->function == VK_LAYER_LINK_INFO) {
                nextGDPA = layerInfo->u.pLayerInfo->pfnNextGetDeviceProcAddr;
                layerInfo->u.pLayerInfo = layerInfo->u.pLayerInfo->pNext;
                break;
            }
        }
        pChain = pChain->pNext;
    }

    // Filter blacklisted extensions
    std::vector<const char*> filteredExts;
    int filteredCount = 0;

    if (pCreateInfo && pCreateInfo->enabledExtensionCount > 0) {
        for (uint32_t i = 0; i < pCreateInfo->enabledExtensionCount; i++) {
            const char* ext = pCreateInfo->ppEnabledExtensionNames[i];
            bool blacklisted = false;
            for (int j = 0; j < BLACKLISTED_EXTENSION_COUNT; j++) {
                if (strcmp(ext, BLACKLISTED_EXTENSIONS[j]) == 0) {
                    LOGI("BLACKLIST: %s", ext);
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
    }

    // Build modified create info if we filtered anything
    VkDeviceCreateInfo modifiedInfo = *pCreateInfo;
    if (filteredCount > 0) {
        LOGI("Filtered %d/%u extensions", filteredCount, pCreateInfo->enabledExtensionCount);
        modifiedInfo.enabledExtensionCount = (uint32_t)filteredExts.size();
        modifiedInfo.ppEnabledExtensionNames = filteredExts.data();
    }

    // Call the real vkCreateDevice
    VkResult result = instDispatch->create_device(
        physicalDevice, &modifiedInfo, pAllocator, pDevice);
    if (result != VK_SUCCESS) {
        LOGE("vkCreateDevice failed: %d", result);
        return result;
    }

    // Populate device dispatch table
    DeviceDispatch devDispatch;
    devDispatch.get_device_proc_addr = nextGDPA;
    if (nextGDPA) {
        devDispatch.cmd_bind_descriptor_sets =
            (PFN_vkCmdBindDescriptorSets)nextGDPA(*pDevice, "vkCmdBindDescriptorSets");
        devDispatch.allocate_descriptor_sets =
            (PFN_vkAllocateDescriptorSets)nextGDPA(*pDevice, "vkAllocateDescriptorSets");
        devDispatch.destroy_device =
            (PFN_vkDestroyDevice)nextGDPA(*pDevice, "vkDestroyDevice");
    }

    g_device_dispatch.push_back({*pDevice, devDispatch});

    LOGI("Device created: %p, dispatch populated", (void*)*pDevice);
    return VK_SUCCESS;
}

// =============================================================================
// vkDestroyDevice — cleanup device dispatch
// =============================================================================

VKAPI_ATTR void VKAPI_CALL aurora_vkDestroyDevice(
    VkDevice device,
    const VkAllocationCallbacks* pAllocator)
{
    DeviceDispatch* dispatch = get_device_dispatch(device);
    if (dispatch && dispatch->destroy_device) {
        dispatch->destroy_device(device, pAllocator);
    }

    for (auto it = g_device_dispatch.begin(); it != g_device_dispatch.end(); ++it) {
        if (it->first == device) {
            g_device_dispatch.erase(it);
            break;
        }
    }
}

// =============================================================================
// vkCmdBindDescriptorSets — split >4 sets (Mali crashes on >4)
// =============================================================================

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
    // Get the device that owns this command buffer
    // (For simplicity, use the first device — typically only one)
    DeviceDispatch* dispatch = nullptr;
    if (!g_device_dispatch.empty()) {
        dispatch = &g_device_dispatch[0].second;
    }

    if (!dispatch || !dispatch->cmd_bind_descriptor_sets) {
        LOGE("No device dispatch for vkCmdBindDescriptorSets!");
        return;
    }

    if (descriptorSetCount <= MAX_DESCRIPTOR_SETS_PER_CALL) {
        dispatch->cmd_bind_descriptor_sets(commandBuffer, pipelineBindPoint, layout,
            firstSet, descriptorSetCount, pDescriptorSets,
            dynamicOffsetCount, pDynamicOffsets);
        return;
    }

    // Split into chunks of MAX_DESCRIPTOR_SETS_PER_CALL
    LOGI("Split vkCmdBindDescriptorSets: %u sets -> chunks of %u",
         descriptorSetCount, MAX_DESCRIPTOR_SETS_PER_CALL);
    stats_descriptor_sets_split++;

    // Note: dynamic offsets are NOT split correctly here.
    // This is a known limitation — proper splitting requires knowing
    // how many dynamic offsets each descriptor set consumes, which
    // requires inspecting the descriptor set layouts. For now, we
    // pass all dynamic offsets to the first chunk and none to the rest.
    // This works for the common case (most games use 0-2 dynamic offsets).
    uint32_t remaining = descriptorSetCount;
    uint32_t offset = 0;
    uint32_t setOffset = firstSet;

    while (remaining > 0) {
        uint32_t chunk = (remaining > MAX_DESCRIPTOR_SETS_PER_CALL)
                       ? MAX_DESCRIPTOR_SETS_PER_CALL : remaining;

        uint32_t dynOffs = (offset == 0) ? dynamicOffsetCount : 0;
        const uint32_t* dynPtr = (offset == 0) ? pDynamicOffsets : nullptr;

        dispatch->cmd_bind_descriptor_sets(commandBuffer, pipelineBindPoint, layout,
            setOffset, chunk, pDescriptorSets + offset,
            dynOffs, dynPtr);

        offset += chunk;
        setOffset += chunk;
        remaining -= chunk;
    }
}

// =============================================================================
// vkGetInstanceProcAddr — dispatch to our hooks or pass through
// =============================================================================

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL aurora_vkGetInstanceProcAddr(
    VkInstance instance, const char* pName)
{
    // Intercept instance-level functions
    if (strcmp(pName, "vkCreateInstance") == 0)
        return (PFN_vkVoidFunction)aurora_vkCreateInstance;
    if (strcmp(pName, "vkDestroyInstance") == 0)
        return (PFN_vkVoidFunction)aurora_vkDestroyInstance;
    if (strcmp(pName, "vkCreateDevice") == 0)
        return (PFN_vkVoidFunction)aurora_vkCreateDevice;
    if (strcmp(pName, "vkGetInstanceProcAddr") == 0)
        return (PFN_vkVoidFunction)aurora_vkGetInstanceProcAddr;
    if (strcmp(pName, "vkGetDeviceProcAddr") == 0)
        return (PFN_vkVoidFunction)aurora_vkGetDeviceProcAddr;

    // Pass through to next layer
    if (instance) {
        InstanceDispatch* dispatch = get_instance_dispatch(instance);
        if (dispatch && dispatch->get_instance_proc_addr) {
            return dispatch->get_instance_proc_addr(instance, pName);
        }
    }
    return nullptr;
}

// =============================================================================
// vkGetDeviceProcAddr — dispatch to our device-level hooks
// =============================================================================

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL aurora_vkGetDeviceProcAddr(
    VkDevice device, const char* pName)
{
    if (strcmp(pName, "vkCmdBindDescriptorSets") == 0)
        return (PFN_vkVoidFunction)aurora_vkCmdBindDescriptorSets;
    if (strcmp(pName, "vkDestroyDevice") == 0)
        return (PFN_vkVoidFunction)aurora_vkDestroyDevice;
    if (strcmp(pName, "vkGetDeviceProcAddr") == 0)
        return (PFN_vkVoidFunction)aurora_vkGetDeviceProcAddr;

    // Pass through to next layer
    if (device) {
        DeviceDispatch* dispatch = get_device_dispatch(device);
        if (dispatch && dispatch->get_device_proc_addr) {
            return dispatch->get_device_proc_addr(device, pName);
        }
    }
    return nullptr;
}

// =============================================================================
// Layer negotiation — called by Vulkan loader
// =============================================================================

typedef struct {
    uint32_t sType;
    void* pNext;
    uint32_t loaderLayerInterfaceVersion;
    PFN_vkGetInstanceProcAddr pfnGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr pfnGetDeviceProcAddr;
    void* pfnGetPhysicalDeviceProcAddr; // NDK doesn't have this type
} VkNegotiateLayerInterface;

#define VK_LUNARG_NEGOTIATE_LAYER_INTERFACE_VERSION_2 2

VKAPI_ATTR VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(
    VkNegotiateLayerInterface* pVersion)
{
    LOGI("=== Aurora Mali Sanitizer Layer Loaded ===");
    LOGI("Rules: %d blacklisted extensions, descriptor set split at %u",
         BLACKLISTED_EXTENSION_COUNT, MAX_DESCRIPTOR_SETS_PER_CALL);

    pVersion->loaderLayerInterfaceVersion = VK_LUNARG_NEGOTIATE_LAYER_INTERFACE_VERSION_2;
    pVersion->pfnGetInstanceProcAddr = aurora_vkGetInstanceProcAddr;
    pVersion->pfnGetDeviceProcAddr = aurora_vkGetDeviceProcAddr;
    pVersion->pfnGetPhysicalDeviceProcAddr = nullptr;

    return VK_SUCCESS;
}

// Fallback entry point
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(
    VkInstance instance, const char* pName)
{
    if (pName && strcmp(pName, "vkNegotiateLoaderLayerInterfaceVersion") == 0) {
        return (PFN_vkVoidFunction)vkNegotiateLoaderLayerInterfaceVersion;
    }
    return aurora_vkGetInstanceProcAddr(instance, pName);
}
