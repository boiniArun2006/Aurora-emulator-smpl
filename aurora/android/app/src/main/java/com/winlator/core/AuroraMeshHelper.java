package com.winlator.core;

import android.content.Context;
import android.util.Log;

import com.winlator.xenvironment.ImageFs;

import java.io.File;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.nio.IntBuffer;

/**
 * Aurora Mesh Engine Helper
 *
 * Manages AOT mesh simplification during container creation.
 * Uses meshoptimizer (native C++) to simplify game meshes at multiple
 * LOD levels via QEM (Quadric Error Metrics).
 *
 * Phase 2 integration into GameNative.
 *
 * Flow:
 * 1. During container creation, scans game directory for .obj files
 *    (or .glb — future, needs glTF parser)
 * 2. For each mesh, simplifies at 4 LOD levels (100%, 50%, 25%, 10%)
 * 3. Saves LODs to aurora_meshes/ cache directory
 * 4. At runtime, DXVK/Wine can pick the appropriate LOD based on
 *    screen-space size (distance from camera)
 *
 * Benefits:
 * - Lower-end devices can use LOD2/LOD3 (25%/10% triangles)
 * - Faster rendering (fewer triangles = less GPU work)
 * - Smaller memory footprint
 * - Especially valuable for Mali GPUs (less fill rate)
 */
public class AuroraMeshHelper {
    private static final String TAG = "AuroraMesh";

    private static boolean nativeLoaded = false;

    static {
        try {
            System.loadLibrary("aurora_mesh");
            nativeLoaded = true;
            Log.i(TAG, "Native mesh library loaded");
        } catch (UnsatisfiedLinkError e) {
            Log.w(TAG, "Native mesh library not available: " + e.getMessage());
            nativeLoaded = false;
        }
    }

    // Native method
    private static native int[] nativeSimplify(
            float[] vertices, int vertexCount,
            int[] indices, int indexCount,
            float targetRatio, float targetError);

    /**
     * Process meshes for a game container.
     * Scans for .obj files and simplifies them at multiple LOD levels.
     *
     * @param context Android context
     * @param gameDirPath Path to the game's A: drive
     * @return Number of meshes processed
     */
    public static int processMeshes(Context context, String gameDirPath) {
        if (!nativeLoaded) {
            Log.w(TAG, "Native library not loaded — skipping mesh processing");
            return 0;
        }

        ImageFs imageFs = ImageFs.find(context);
        File gameDir = new File(gameDirPath);
        if (!gameDir.isDirectory()) {
            Log.w(TAG, "Game directory not found: " + gameDirPath);
            return 0;
        }

        File lodCacheDir = new File(imageFs.cache_path + "/aurora_meshes");
        lodCacheDir.mkdirs();

        Log.i(TAG, "Scanning for .obj files in: " + gameDirPath);
        Log.i(TAG, "LOD cache dir: " + lodCacheDir.getPath());

        // Find .obj files (recursive, max depth 5)
        java.util.List<File> objFiles = new java.util.ArrayList<>();
        findObjFiles(gameDir, 0, 5, objFiles);
        Log.i(TAG, "Found " + objFiles.size() + " .obj files");

        int processed = 0;
        for (File objFile : objFiles) {
            try {
                // Parse OBJ file (simple parser: only vertices + faces)
                MeshData mesh = parseObj(objFile);
                if (mesh == null || mesh.indexCount < 6) {
                    Log.d(TAG, "Skipping (too small or invalid): " + objFile.getName());
                    continue;
                }

                Log.i(TAG, "Processing: " + objFile.getName() +
                      " (" + mesh.vertexCount + " verts, " +
                      (mesh.indexCount / 3) + " tris)");

                // Simplify at 3 LOD levels
                float[] ratios = {0.50f, 0.25f, 0.10f};
                String[] lodNames = {"LOD1", "LOD2", "LOD3"};

                for (int i = 0; i < ratios.length; i++) {
                    int[] result = nativeSimplify(
                            mesh.vertices, mesh.vertexCount,
                            mesh.indices, mesh.indexCount,
                            ratios[i], 0.01f);

                    if (result != null && result.length > 1) {
                        int newCount = result[0];
                        Log.d(TAG, "  " + lodNames[i] + ": " +
                              (mesh.indexCount / 3) + " -> " +
                              (newCount / 3) + " tris");

                        // Save the simplified mesh as a .obj file
                        String baseName = objFile.getName().replace(".obj", "");
                        File lodFile = new File(lodCacheDir, baseName + "_" + lodNames[i] + ".obj");
                        int[] lodIndices = new int[newCount];
                        System.arraycopy(result, 1, lodIndices, 0, newCount);
                        writeObj(lodFile, mesh.vertices, mesh.vertexCount, lodIndices, newCount);
                        Log.d(TAG, "  Saved: " + lodFile.getPath());
                    }
                }
                processed++;
            } catch (Exception e) {
                Log.w(TAG, "Failed to process " + objFile.getName() + ": " + e.getMessage());
            }
        }

        Log.i(TAG, "Mesh processing complete: " + processed + " meshes processed");
        return processed;
    }

    // ---- OBJ parser (simplified — positions + faces only) ----

    private static class MeshData {
        float[] vertices;  // [x0,y0,z0, x1,y1,z1, ...]
        int vertexCount;
        int[] indices;     // [i0,i1,i2, i3,i4,i5, ...]
        int indexCount;
    }

    private static MeshData parseObj(File objFile) {
        try {
            java.util.List<Float> verts = new java.util.ArrayList<>();
            java.util.List<Integer> faces = new java.util.ArrayList<>();

            java.io.BufferedReader reader = new java.io.BufferedReader(
                    new java.io.FileReader(objFile));
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.startsWith("v ")) {
                    // Vertex: "v x y z"
                    String[] parts = line.split("\\s+");
                    if (parts.length >= 4) {
                        verts.add(Float.parseFloat(parts[1]));
                        verts.add(Float.parseFloat(parts[2]));
                        verts.add(Float.parseFloat(parts[3]));
                    }
                } else if (line.startsWith("f ")) {
                    // Face: "f i0 i1 i2" or "f i0 i1 i2 i3" (quad) or more (n-gon)
                    // OBJ indices are 1-based. Handle v/vt/vn format too.
                    String[] parts = line.split("\\s+");
                    java.util.List<Integer> faceIndices = new java.util.ArrayList<>();
                    for (int i = 1; i < parts.length; i++) {
                        String idxStr = parts[i].split("/")[0];
                        try {
                            int idx = Integer.parseInt(idxStr);
                            if (idx < 0) idx = verts.size() / 3 + idx + 2; // negative = relative
                            else idx = idx - 1; // convert 1-based to 0-based
                            if (idx >= 0) faceIndices.add(idx);
                        } catch (NumberFormatException e) {
                            // skip non-numeric
                        }
                    }
                    // Fan-triangulate: if the face has >3 vertices, split into triangles
                    // (v0, v1, v2), (v0, v2, v3), (v0, v3, v4), ...
                    if (faceIndices.size() >= 3) {
                        for (int i = 1; i < faceIndices.size() - 1; i++) {
                            faces.add(faceIndices.get(0));
                            faces.add(faceIndices.get(i));
                            faces.add(faceIndices.get(i + 1));
                        }
                    }
                }
            }
            reader.close();

            if (verts.isEmpty() || faces.isEmpty()) return null;

            MeshData mesh = new MeshData();
            mesh.vertexCount = verts.size() / 3;
            mesh.vertices = new float[verts.size()];
            for (int i = 0; i < verts.size(); i++) mesh.vertices[i] = verts.get(i);
            mesh.indexCount = faces.size();
            mesh.indices = new int[faces.size()];
            for (int i = 0; i < faces.size(); i++) mesh.indices[i] = faces.get(i);
            return mesh;
        } catch (Exception e) {
            Log.w(TAG, "OBJ parse failed: " + e.getMessage());
            return null;
        }
    }

    /**
     * Write a mesh to a Wavefront .obj file.
     * Writes vertices (v x y z) and triangular faces (f i0 i1 i2).
     * The consumer of this output is the game's LOD loading system,
     * which picks the appropriate LOD based on screen-space size.
     */
    private static void writeObj(File outFile, float[] vertices, int vertexCount,
                                  int[] indices, int indexCount) {
        try {
            java.io.PrintWriter writer = new java.io.PrintWriter(outFile);
            writer.println("# Aurora Mesh Engine — QEM simplified LOD");
            writer.println("# vertices: " + vertexCount + ", triangles: " + (indexCount / 3));

            // Write vertices (1-indexed in OBJ)
            for (int i = 0; i < vertexCount; i++) {
                writer.printf("v %.6f %.6f %.6f%n",
                    vertices[i * 3], vertices[i * 3 + 1], vertices[i * 3 + 2]);
            }

            // Write faces (1-indexed)
            for (int i = 0; i < indexCount; i += 3) {
                writer.printf("f %d %d %d%n",
                    indices[i] + 1, indices[i + 1] + 1, indices[i + 2] + 1);
            }

            writer.close();
        } catch (Exception e) {
            Log.e(TAG, "Failed to write OBJ: " + e.getMessage());
        }
    }

    private static void findObjFiles(File dir, int depth, int maxDepth,
                                      java.util.List<File> results) {
        if (depth > maxDepth) return;
        File[] files = dir.listFiles();
        if (files == null) return;
        for (File f : files) {
            if (f.isFile() && f.getName().toLowerCase().endsWith(".obj")) {
                results.add(f);
            } else if (f.isDirectory()) {
                findObjFiles(f, depth + 1, maxDepth, results);
            }
        }
    }

    public static boolean isAvailable() {
        return nativeLoaded;
    }
}
