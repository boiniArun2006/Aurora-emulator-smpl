package com.winlator.core;

import android.content.Context;
import android.util.Log;

import com.winlator.core.aurora.MarkovModel;
import com.winlator.container.Container;
import com.winlator.core.envvars.EnvVars;
import com.winlator.xenvironment.ImageFs;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.List;

/**
 * Aurora Prefetch Helper
 *
 * Manages the Markov-based predictive file prefetcher.
 *
 * Phase 3 integration into GameNative.
 *
 * How it works:
 * 1. On first game launch: no model exists. A future C library (LD_PRELOAD)
 *    logs file accesses to a trace file inside the PRoot environment.
 * 2. After game session: this helper reads the trace, trains a Markov model,
 *    and saves it to the Aurora cache directory.
 * 3. On subsequent launches: the model is loaded. Env vars are set so the
 *    C library knows where to find the model + which files to prefetch.
 *
 * The actual file I/O interception requires a C library loaded via
 * LD_PRELOAD inside the glibc/PRoot environment. This helper sets up
 * the infrastructure (model + env vars) for that library.
 *
 * STUB NOTICE: The LD_PRELOAD C library (libaurora_prefetch.so) that
 * would log file accesses and perform posix_fadvise() prefetching
 * DOES NOT EXIST YET. As a result:
 *   - setupPrefetcher() works (sets env vars) but the env vars are
 *     consumed by nothing at runtime — no file access logging happens.
 *   - processTrace() will always find an empty/missing trace file
 *     and return false. The Markov model is never trained.
 *   - The MarkovModel.kt class itself is fully implemented and tested,
 *     but has no data source feeding it.
 * Until libaurora_prefetch.so is built (requires glibc cross-compile,
 * same as libredirect.so that GameNative already uses), this entire
 * phase is infrastructure-only — it sets up env vars that a future
 * C library will read, but no C library reads them today.
 *
 * Algorithm reference:
 *   Patterson et al. 1995, "Informed Prefetching and Caching", SOSP '95
 */
public class AuroraPrefetchHelper {
    private static final String TAG = "AuroraPrefetch";

    // Default threshold: only prefetch files with >30% transition probability
    private static final double DEFAULT_THRESHOLD = 0.30;

    /**
     * Set up the prefetcher for a game launch.
     * Sets env vars so the LD_PRELOAD library knows where to find the model.
     *
     * @param context Android context
     * @param container Game container
     * @param envVars EnvVars to modify
     * @return true if prefetcher is active (model exists or will record)
     */
    public static boolean setupPrefetcher(
            Context context,
            Container container,
            EnvVars envVars) {

        ImageFs imageFs = ImageFs.find(context);

        // Create prefetch cache directory
        File prefetchDir = new File(imageFs.cache_path + "/aurora_prefetch");
        prefetchDir.mkdirs();

        // Model file path (per-game)
        File modelFile = new File(prefetchDir, container.id + "_model.json");

        // Trace file path (where the C library logs file accesses)
        File traceFile = new File(prefetchDir, container.id + "_trace.log");

        Log.i(TAG, "Setting up prefetcher for container: " + container.id);
        Log.i(TAG, "  Model: " + modelFile.getPath() + (modelFile.exists() ? " (exists)" : " (will create)"));
        Log.i(TAG, "  Trace: " + traceFile.getPath());

        // Set env vars for the LD_PRELOAD library (when it exists)
        envVars.put("AURORA_PREFETCH_ENABLED", "1");
        envVars.put("AURORA_PREFETCH_MODEL", modelFile.getPath());
        envVars.put("AURORA_PREFETCH_TRACE", traceFile.getPath());
        envVars.put("AURORA_PREFETCH_THRESHOLD", String.valueOf(DEFAULT_THRESHOLD));

        if (modelFile.exists()) {
            Log.i(TAG, "  Model found — prefetcher will use predictions");
            envVars.put("AURORA_PREFETCH_MODE", "predict");
        } else {
            Log.i(TAG, "  No model yet — first launch will record trace");
            envVars.put("AURORA_PREFETCH_MODE", "record");
        }

        return true;
    }

    /**
     * Process a play trace after a game session.
     * Reads the trace file, trains a Markov model, saves it.
     *
     * @param context Android context
     * @param containerId Game container ID
     * @return true if model was trained successfully
     */
    public static boolean processTrace(Context context, String containerId) {
        ImageFs imageFs = ImageFs.find(context);
        File prefetchDir = new File(imageFs.cache_path + "/aurora_prefetch");
        File traceFile = new File(prefetchDir, containerId + "_trace.log");
        File modelFile = new File(prefetchDir, containerId + "_model.json");

        if (!traceFile.exists()) {
            Log.i(TAG, "No trace file found: " + traceFile.getPath());
            return false;
        }

        Log.i(TAG, "Processing play trace: " + traceFile.getPath());

        // Read the trace file (one file path per line)
        List<String> trace = new ArrayList<>();
        try {
            BufferedReader reader = new BufferedReader(new FileReader(traceFile));
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (!line.isEmpty()) {
                    trace.add(line);
                }
            }
            reader.close();
        } catch (Exception e) {
            Log.e(TAG, "Failed to read trace: " + e.getMessage());
            return false;
        }

        if (trace.size() < 10) {
            Log.i(TAG, "Trace too small (" + trace.size() + " accesses) — skipping training");
            return false;
        }

        Log.i(TAG, "Trace has " + trace.size() + " file accesses");

        // Load existing model (if any) and merge with new trace
        MarkovModel model = new MarkovModel(DEFAULT_THRESHOLD);
        if (modelFile.exists()) {
            model.load(modelFile);
        }

        // Train with new trace
        model.train(trace);

        // Save updated model
        model.save(modelFile);

        // Print stats
        Log.i(TAG, "Model updated: " + model.stats());

        // Optionally clear the trace file (keep it for incremental training)
        // traceFile.delete();

        return true;
    }

    /**
     * Check if a trained model exists for a game.
     */
    public static boolean hasModel(Context context, String containerId) {
        ImageFs imageFs = ImageFs.find(context);
        File modelFile = new File(imageFs.cache_path + "/aurora_prefetch",
                containerId + "_model.json");
        return modelFile.exists();
    }
}
