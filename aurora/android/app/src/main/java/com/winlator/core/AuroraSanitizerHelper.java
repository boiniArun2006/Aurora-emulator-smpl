package com.winlator.core;

import android.content.Context;
import android.util.Log;

import com.winlator.xenvironment.ImageFs;
import com.winlator.core.envvars.EnvVars;

import java.io.File;

/**
 * Aurora Mali Sanitizer Helper
 *
 * Sets up the Vulkan layer environment variables when the GPU is Mali.
 * Called from GlibcProgramLauncherComponent.addBox64EnvVars() before
 * launching the game.
 *
 * Two modes:
 * 1. Full mode (when .so is available): Sets VK_INSTANCE_LAYERS to load
 *    the Vulkan layer that intercepts all calls and applies 10 rules.
 *
 * 2. Fallback mode (when .so is not available): Modifies DXVK_CONFIG to
 *    avoid requesting features that crash Mali, achieving similar results
 *    without a native layer.
 *
 * Phase 6 integration into GameNative.
 */
public class AuroraSanitizerHelper {
    private static final String TAG = "AuroraSanitizer";

    /**
     * DXVK config settings to add when running on Mali (fallback mode).
     * These prevent DXVK from requesting Vulkan extensions that crash Mali.
     */
    private static final String MALI_DXVK_CONFIG =
        "dxvk.useDescriptorIndexing = False;" +     // Avoid VK_EXT_descriptor_indexing (MALI-001)
        "dxvk.usePipelineLibrary = False;" +        // Avoid VK_EXT_graphics_pipeline_library (MALI-004)
        "d3d11.maxFeatureLevel = 11_0;" +           // Don't request 12_0+ (needs subgroups on Mali)
        "d3d11.relaxedBarriers = True;" +           // Workaround for Mali TBDR tile resolves
        "dxvk.shaderUseSubgroupOps = False";        // Avoid VK_KHR_shader_subgroup (MALI-003)

    /**
     * Set up the Mali sanitizer for the game launch.
     *
     * @param context Android context
     * @param envVars EnvVars to modify
     * @param imageFs ImageFs instance
     * @param gpuRenderer GPU renderer string (e.g. "Mali-G610")
     * @return true if sanitizer was enabled, false if not needed (non-Mali GPU)
     */
    public static boolean setupSanitizer(
            Context context,
            EnvVars envVars,
            ImageFs imageFs,
            String gpuRenderer) {

        if (gpuRenderer == null || !gpuRenderer.contains("Mali")) {
            return false; // Not a Mali GPU — no sanitizer needed
        }

        Log.i(TAG, "Mali GPU detected: " + gpuRenderer + " — enabling sanitizer");

        // Check if the sanitizer .so exists in imagefs
        File sanitizerSo = new File(imageFs.getRootDir(), "usr/lib/libaurora_mali_sanitizer.so");

        if (sanitizerSo.exists()) {
            // Full sanitizer mode — load the Vulkan layer
            Log.i(TAG, "Sanitizer .so found — full Vulkan layer mode");
            envVars.put("VK_INSTANCE_LAYERS", "libaurora_mali_sanitizer.so");
            envVars.put("VK_LAYER_PATH", imageFs.getRootDir().getPath() + "/usr/lib");
            envVars.put("AURORA_MALI_SANITIZER", "1");
            return true;
        }

        // Fallback: modify DXVK config to avoid requesting blacklisted extensions
        Log.i(TAG, "Sanitizer .so not found — using DXVK config fallback");
        envVars.put("AURORA_MALI_SANITIZER", "fallback");

        // Get existing DXVK_CONFIG and append our Mali workarounds
        String existingConfig = envVars.get("DXVK_CONFIG");
        if (existingConfig.isEmpty()) {
            envVars.put("DXVK_CONFIG", "\"" + MALI_DXVK_CONFIG + "\"");
        } else {
            // Append to existing config (strip trailing quote, add our settings, re-add quote)
            String stripped = existingConfig.replace("\"", "");
            if (!stripped.endsWith(";") && !stripped.endsWith("\n")) {
                stripped += ";";
            }
            envVars.put("DXVK_CONFIG", "\"" + stripped + MALI_DXVK_CONFIG + "\"");
        }

        Log.i(TAG, "DXVK_CONFIG updated with Mali workarounds: " + MALI_DXVK_CONFIG);
        return true;
    }
}
