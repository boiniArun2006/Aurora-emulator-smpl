package com.winlator.core.aurora

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.ConcurrentHashMap

/**
 * Aurora Markov Prefetcher Model
 *
 * A Markov-chain-based predictive file prefetcher.
 * Learns file access patterns from play traces and predicts
 * which files will be accessed next.
 *
 * Algorithm reference:
 *   Patterson et al. 1995, "Informed Prefetching and Caching", SOSP '95
 *   Kroeger & Long 1996, "Predicting File-System Actions"
 *
 * Phase 3 integration into GameNative.
 *
 * Architecture:
 * - transitions[fileA][fileB] = count of times fileB followed fileA
 * - totals[fileA] = total transitions out of fileA
 * - P(fileB | fileA) = transitions[fileA][fileB] / totals[fileA]
 *
 * At runtime, after accessing fileA, we look up transitions[fileA]
 * and prefetch files where P > threshold (default 0.30).
 */
class MarkovModel(
    private val prefetchThreshold: Double = 0.30
) {
    companion object {
        private const val TAG = "AuroraMarkov"
    }

    // transitions[A][B] = number of times B followed A
    private val transitions = ConcurrentHashMap<String, MutableMap<String, Int>>()

    // totals[A] = total count of transitions out of A
    private val totals = ConcurrentHashMap<String, Int>()

    /**
     * Train the model from a list of file access paths (in chronological order).
     */
    fun train(trace: List<String>) {
        if (trace.size < 2) return

        Log.i(TAG, "Training Markov model from ${trace.size} accesses")

        for (i in 0 until trace.size - 1) {
            val current = trace[i]
            val next = trace[i + 1]
            transitions.getOrPut(current) { mutableMapOf() }
                .merge(next, 1) { old, _ -> old + 1 }
            totals.merge(current, 1) { old, _ -> old + 1 }
        }

        val states = transitions.size
        val edgeCount = transitions.values.sumOf { it.size }
        Log.i(TAG, "Model trained: $states states, $edgeCount transitions")
    }

    /**
     * Predict the next files given the current file.
     * Returns list of (file, probability) pairs where P > threshold.
     */
    fun predict(currentFile: String): List<Pair<String, Double>> {
        val trans = transitions[currentFile] ?: return emptyList()
        val total = totals[currentFile] ?: return emptyList()
        if (total == 0) return emptyList()

        return trans.entries
            .map { (file, count) -> file to count.toDouble() / total }
            .filter { it.second >= prefetchThreshold }
            .sortedByDescending { it.second }
    }

    /**
     * Save the model to a JSON file.
     */
    fun save(file: File) {
        val json = JSONObject()
        json.put("threshold", prefetchThreshold)

        val transJson = JSONObject()
        for ((from, targets) in transitions) {
            val targetJson = JSONObject()
            for ((to, count) in targets) {
                targetJson.put(to, count)
            }
            transJson.put(from, targetJson)
        }
        json.put("transitions", transJson)

        val totalsJson = JSONObject()
        for ((file, count) in totals) {
            totalsJson.put(file, count)
        }
        json.put("totals", totalsJson)

        json.put("stats", JSONObject().apply {
            put("states", transitions.size)
            put("transitions", transitions.values.sumOf { it.size })
        })

        file.parentFile?.mkdirs()
        file.writeText(json.toString(2))
        Log.i(TAG, "Model saved: ${file.path} (${file.length()} bytes)")
    }

    /**
     * Load a model from a JSON file.
     */
    fun load(file: File): Boolean {
        if (!file.exists()) return false
        try {
            val json = JSONObject(file.readText())
            val transJson = json.optJSONObject("transitions") ?: return false
            val totalsJson = json.optJSONObject("totals") ?: return false

            transitions.clear()
            totals.clear()

            for (from in transJson.keys()) {
                val targetJson = transJson.getJSONObject(from)
                val targetMap = mutableMapOf<String, Int>()
                for (to in targetJson.keys()) {
                    targetMap[to] = targetJson.getInt(to)
                }
                transitions[from] = targetMap
            }

            for (file in totalsJson.keys()) {
                totals[file] = totalsJson.getInt(file)
            }

            Log.i(TAG, "Model loaded: ${transitions.size} states from ${file.path}")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to load model: ${e.message}")
            return false
        }
    }

    /**
     * Get model statistics.
     */
    fun stats(): Map<String, Int> = mapOf(
        "states" to transitions.size,
        "transitions" to transitions.values.sumOf { it.size }
    )
}
