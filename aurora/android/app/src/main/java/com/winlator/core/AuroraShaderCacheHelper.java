package com.winlator.core;

import android.content.Context;
import android.util.Log;

import com.winlator.container.Container;
import com.winlator.core.envvars.EnvVars;
import com.winlator.xenvironment.ImageFs;

import java.io.File;

/**
 * Aurora Shader Cache Helper
 *
 * Manages the DXVK state cache for per-game shader pre-caching.
 *
 * Phase 4 integration into GameNative.
 *
 * What it does:
 * 1. Creates a per-game subdirectory for DXVK state cache
 *    (instead of the shared cache path GameNative uses by default)
 * 2. Checks if a pre-downloaded cloud cache exists for this game+GPU
 * 3. If yes, symlinks/copies it to the active cache path
 * 4. After game session, the cache is preserved for next launch
 *
 * Cloud sync (download from community cache) requires a backend service.
 * For now, this helper sets up the per-game cache structure. When a cloud
 * backend is available, the downloadIfAvailable() method will fetch caches.
 */
public class AuroraShaderCacheHelper {
    private static final String TAG = "AuroraShaderCache";

    /**
     * Set up the shader cache for a specific game.
     *
     * @param context Android context
     * @param container The game's container (has game ID + config)
     * @param envVars EnvVars to modify (sets DXVK_STATE_CACHE_PATH)
     * @return The cache path that was set up
     */
    public static String setupCache(
            Context context,
            Container container,
            EnvVars envVars) {

        ImageFs imageFs = ImageFs.find(context);
        String renderer = GPUInformation.getRenderer(context);

        // Create per-game cache directory
        // Format: <imagefs>/home/xuser/.cache/aurora_shaders/<container_id>/
        String gameId = container.id;
        File cacheDir = new File(imageFs.cache_path + "/aurora_shaders/" + gameId);
        cacheDir.mkdirs();

        Log.i(TAG, "Setting up shader cache for container: " + gameId);
        Log.i(TAG, "  Cache dir: " + cacheDir.getPath());
        Log.i(TAG, "  GPU: " + renderer);

        // Check if a pre-downloaded cloud cache exists
        File cloudCache = new File(cacheDir, "dxvk_state_cache.bin");
        if (cloudCache.exists()) {
            Log.i(TAG, "  Pre-downloaded cloud cache found: " + cloudCache.length() + " bytes");
        } else {
            Log.i(TAG, "  No cloud cache yet — first launch will compile shaders on-demand");
            // TODO: When cloud backend is available, download cache here:
            // downloadCloudCache(gameId, renderer, cacheDir);
        }

        // Set DXVK_STATE_CACHE_PATH to our per-game directory
        // DXVK writes .dxvk-cache files here
        String cachePath = cacheDir.getPath();
        envVars.put("DXVK_STATE_CACHE_PATH", cachePath);
        envVars.put("AURORA_SHADER_CACHE_PATH", cachePath);

        Log.i(TAG, "  DXVK_STATE_CACHE_PATH=" + cachePath);
        return cachePath;
    }

    /**
     * Check if a cloud shader cache is available for this game+GPU.
     * In production, this would query a cloud service.
     * For now, returns false (no cloud backend yet).
     */
    public static boolean isCloudCacheAvailable(String gameId, String gpuRenderer) {
        // TODO: Query cloud service (e.g., https://cloud.aurora-emulator.org/api/shaders/<gameId>)
        // For now, always return false — users compile their own shaders on first launch
        return false;
    }

    /**
     * Upload newly encountered shaders to the cloud after a game session.
     * In production, this would POST the shader cache to a cloud service.
     * For now, just logs.
     */
    public static void uploadCacheToCloud(String gameId, String gpuRenderer, File cacheDir) {
        if (!cacheDir.exists()) return;

        File[] cacheFiles = cacheDir.listFiles((dir, name) ->
            name.endsWith(".dxvk-cache") || name.endsWith(".bin"));

        if (cacheFiles == null || cacheFiles.length == 0) {
            Log.i(TAG, "No shader cache files to upload");
            return;
        }

        long totalSize = 0;
        for (File f : cacheFiles) {
            totalSize += f.length();
        }

        Log.i(TAG, "Shader cache ready for upload: " + cacheFiles.length +
              " files, " + (totalSize / 1024) + " KB");
        Log.i(TAG, "  (Cloud upload not yet implemented — caches stored locally)");

        // TODO: When cloud backend is available:
        // 1. Hash each cache file
        // 2. POST to cloud service with (gameId, gpuRenderer, hash, file)
        // 3. Cloud deduplicates by hash
    }
}
