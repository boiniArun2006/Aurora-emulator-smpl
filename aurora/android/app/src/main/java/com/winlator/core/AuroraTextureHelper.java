package com.winlator.core;

import android.content.Context;
import android.util.Log;

import com.winlator.xenvironment.ImageFs;

import java.io.File;

/**
 * Aurora Texture Engine Helper
 *
 * Manages AOT texture transcoding during container creation.
 * Uses Basis Universal's transcoder (native C++) to convert
 * KTX2/UASTC files to ASTC format (mobile GPU native).
 *
 * Phase 1 integration into GameNative.
 *
 * Flow:
 * 1. A PC tool (src/texture_engine/aot_texture_transcoder.py) pre-encodes
 *    game .dds textures to KTX2/UASTC format (supercompressed with zstd)
 * 2. The .ktx2 files are placed alongside game files in the Wine prefix
 * 3. At container creation, this helper scans for .ktx2 files
 * 4. Each .ktx2 is transcoded to .astc via the native library
 * 5. The .astc files are stored in the Aurora texture cache
 * 6. At runtime, DXVK loads the .astc files instead of emulating BCn
 *
 * Benefits:
 * - 3-4x smaller texture storage (KTX2/UASTC + zstd vs raw BCn)
 * - No runtime BCn emulation overhead (ASTC is native on Mali/Adreno)
 * - Faster texture loading (smaller files = faster I/O)
 */
public class AuroraTextureHelper {
    private static final String TAG = "AuroraTexture";

    // Native library loaded once
    private static boolean nativeLoaded = false;

    static {
        try {
            System.loadLibrary("aurora_texture");
            nativeLoaded = true;
            Log.i(TAG, "Native texture library loaded");
        } catch (UnsatisfiedLinkError e) {
            Log.w(TAG, "Native texture library not available: " + e.getMessage());
            nativeLoaded = false;
        }
    }

    // Native method declarations
    private static native boolean nativeInit();
    private static native boolean nativeTranscodeKtx2ToAstc(String inputPath, String outputPath);
    private static native boolean nativeIsKtx2File(String filePath);

    /**
     * Process textures for a game container.
     * Scans the Wine prefix for .ktx2 files and transcodes them to .astc.
     *
     * @param context Android context
     * @param gameDirPath Path to the game's A: drive (inside Wine prefix)
     * @return Number of textures successfully transcoded
     */
    public static int processTextures(Context context, String gameDirPath) {
        if (!nativeLoaded) {
            Log.w(TAG, "Native library not loaded — skipping texture processing");
            return 0;
        }

        // Initialize the transcoder (once)
        if (!nativeInit()) {
            Log.e(TAG, "Failed to initialize Basis Universal transcoder");
            return 0;
        }

        ImageFs imageFs = ImageFs.find(context);
        File gameDir = new File(gameDirPath);
        if (!gameDir.isDirectory()) {
            Log.w(TAG, "Game directory not found: " + gameDirPath);
            return 0;
        }

        // Create output directory for ASTC files
        File astcCacheDir = new File(imageFs.cache_path + "/aurora_textures");
        astcCacheDir.mkdirs();

        Log.i(TAG, "Scanning for .ktx2 files in: " + gameDirPath);
        Log.i(TAG, "ASTC output dir: " + astcCacheDir.getPath());

        // Scan for .ktx2 files (recursive, max depth 5)
        int transcoded = 0;
        int skipped = 0;
        int failed = 0;

        File[] ktx2Files = findKtx2Files(gameDir, 0, 5);
        Log.i(TAG, "Found " + ktx2Files.length + " .ktx2 files");

        for (File ktx2File : ktx2Files) {
            // Generate output path (same relative structure in cache dir)
            String relativePath = getRelativePath(gameDir, ktx2File);
            File astcFile = new File(astcCacheDir, relativePath.replace(".ktx2", ".astc"));
            astcFile.getParentFile().mkdirs();

            // Skip if ASTC already exists and is newer
            if (astcFile.exists() && astcFile.lastModified() > ktx2File.lastModified()) {
                skipped++;
                continue;
            }

            // Validate it's actually a KTX2 file
            if (!nativeIsKtx2File(ktx2File.getPath())) {
                Log.w(TAG, "Not a valid KTX2 file: " + ktx2File.getPath());
                skipped++;
                continue;
            }

            // Transcode
            Log.d(TAG, "Transcoding: " + ktx2File.getName() +
                  " (" + (ktx2File.length() / 1024) + " KB)");

            if (nativeTranscodeKtx2ToAstc(ktx2File.getPath(), astcFile.getPath())) {
                transcoded++;
                Log.d(TAG, "  -> " + astcFile.getName() +
                      " (" + (astcFile.length() / 1024) + " KB)");
            } else {
                failed++;
                Log.e(TAG, "  FAILED to transcode: " + ktx2File.getPath());
            }
        }

        Log.i(TAG, "Texture processing complete: " + transcoded + " transcoded, " +
              skipped + " skipped, " + failed + " failed");

        return transcoded;
    }

    /**
     * Recursively find .ktx2 files up to maxDepth.
     */
    private static File[] findKtx2Files(File dir, int currentDepth, int maxDepth) {
        java.util.List<File> results = new java.util.ArrayList<>();
        findKtx2FilesRecursive(dir, currentDepth, maxDepth, results);
        return results.toArray(new File[0]);
    }

    private static void findKtx2FilesRecursive(File dir, int depth, int maxDepth,
                                                java.util.List<File> results) {
        if (depth > maxDepth) return;
        File[] files = dir.listFiles();
        if (files == null) return;

        for (File f : files) {
            if (f.isFile() && f.getName().toLowerCase().endsWith(".ktx2")) {
                results.add(f);
            } else if (f.isDirectory()) {
                findKtx2FilesRecursive(f, depth + 1, maxDepth, results);
            }
        }
    }

    /**
     * Get the relative path of a file from a base directory.
     */
    private static String getRelativePath(File base, File file) {
        String basePath = base.getAbsolutePath();
        String filePath = file.getAbsolutePath();
        if (filePath.startsWith(basePath)) {
            return filePath.substring(basePath.length() + 1);
        }
        return file.getName();
    }

    /**
     * Check if the native texture library is available.
     */
    public static boolean isAvailable() {
        return nativeLoaded;
    }
}
