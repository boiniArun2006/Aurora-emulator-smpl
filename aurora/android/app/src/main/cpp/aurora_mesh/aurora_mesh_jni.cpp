/*
 * Aurora Mesh Engine JNI Bridge
 * ==============================
 *
 * Provides native mesh simplification via meshoptimizer (QEM algorithm).
 * Reduces triangle count of game meshes at multiple LOD levels.
 *
 * Phase 2 integration into GameNative.
 *
 * Algorithm: Garland & Heckbert 1997, "Surface Simplification Using
 * Quadric Error Metrics" — implemented by meshoptimizer (MIT, Arseny
 * Kapoulkine, used by Horizon Zero Dawn PC port, Call of Duty, etc.)
 */

#include <jni.h>
#include <android/log.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>

#include "meshoptimizer.h"

#define TAG "AuroraMesh"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

#define VERTEX_STRIDE 12  // 3 floats (x,y,z) x 4 bytes
#define SIMPLIFY_LOCK_BORDER (1 << 0)

extern "C" {

JNIEXPORT jintArray JNICALL
Java_com_winlator_core_AuroraMeshHelper_nativeSimplify(
        JNIEnv* env, jclass cls,
        jfloatArray vertices, jint vertexCount,
        jintArray indices, jint indexCount,
        jfloat targetRatio, jfloat targetError) {

    if (indexCount == 0 || vertexCount == 0 || indexCount % 3 != 0) {
        LOGE("Invalid input: vertices=%d, indices=%d", vertexCount, indexCount);
        return nullptr;
    }

    jfloat* verts = env->GetFloatArrayElements(vertices, nullptr);
    jint* idx = env->GetIntArrayElements(indices, nullptr);

    // Validate: all indices must be < vertexCount
    for (int i = 0; i < indexCount; i++) {
        if (idx[i] < 0 || idx[i] >= vertexCount) {
            LOGE("Index %d out of bounds: %d (vertexCount=%d)", i, idx[i], vertexCount);
            env->ReleaseFloatArrayElements(vertices, verts, JNI_ABORT);
            env->ReleaseIntArrayElements(indices, idx, JNI_ABORT);
            return nullptr;
        }
    }

    unsigned int* dstIndices = (unsigned int*)malloc(indexCount * sizeof(unsigned int));
    if (!dstIndices) {
        env->ReleaseFloatArrayElements(vertices, verts, JNI_ABORT);
        env->ReleaseIntArrayElements(indices, idx, JNI_ABORT);
        return nullptr;
    }

    size_t targetIndexCount = (size_t)(indexCount * targetRatio);
    if (targetIndexCount < 3) targetIndexCount = 3;

    float resultError = 0.0f;
    LOGI("Simplifying: %d verts, %d indices -> target %zu (%.0f%%)",
         vertexCount, indexCount, targetIndexCount, targetRatio * 100);

    size_t actualIndexCount = meshopt_simplify(
        dstIndices,
        (const unsigned int*)idx, (size_t)indexCount,
        verts, (size_t)vertexCount, VERTEX_STRIDE,
        targetIndexCount, (float)targetError,
        SIMPLIFY_LOCK_BORDER,
        &resultError
    );

    LOGI("Simplified: %d -> %zu indices (error=%.4f)", indexCount, actualIndexCount, resultError);

    env->ReleaseFloatArrayElements(vertices, verts, JNI_ABORT);
    env->ReleaseIntArrayElements(indices, idx, JNI_ABORT);

    // Output: [0]=count, [1..count]=indices
    jintArray result = env->NewIntArray((jint)(actualIndexCount + 1));
    if (!result) { free(dstIndices); return nullptr; }

    jint count = (jint)actualIndexCount;
    env->SetIntArrayRegion(result, 0, 1, &count);
    env->SetIntArrayRegion(result, 1, (jint)actualIndexCount, (const jint*)dstIndices);

    free(dstIndices);
    return result;
}

} // extern "C"
