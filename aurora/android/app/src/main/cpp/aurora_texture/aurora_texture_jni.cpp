/*
 * Aurora Texture Engine JNI Bridge
 * =================================
 *
 * Provides native texture transcoding via Basis Universal's transcoder.
 * Converts KTX2/UASTC files to ASTC format (mobile GPU native).
 *
 * Phase 1 integration into GameNative.
 *
 * Uses ktx2_transcoder API:
 *   1. ktx2_transcoder::init(data, size) — parse KTX2 header
 *   2. ktx2_transcoder::start_transcoding() — decompress codebooks
 *   3. ktx2_transcoder::transcode_image_level() — transcode each mip level
 */

#include <jni.h>
#include <android/log.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#include "basisu_transcoder.h"

#define TAG "AuroraTexture"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

static bool g_initialized = false;

extern "C" {

JNIEXPORT jboolean JNICALL
Java_com_winlator_core_AuroraTextureHelper_nativeInit(JNIEnv* env, jclass cls) {
    if (g_initialized) return JNI_TRUE;

    LOGI("Initializing Basis Universal transcoder...");
    basist::basisu_transcoder_init();
    g_initialized = true;
    LOGI("Basis Universal transcoder initialized");
    return JNI_TRUE;
}

JNIEXPORT jboolean JNICALL
Java_com_winlator_core_AuroraTextureHelper_nativeTranscodeKtx2ToAstc(
        JNIEnv* env, jclass cls,
        jstring inputPath, jstring outputPath) {

    if (!g_initialized) {
        LOGE("Transcoder not initialized — call nativeInit() first");
        return JNI_FALSE;
    }

    const char* inPath = env->GetStringUTFChars(inputPath, nullptr);
    const char* outPath = env->GetStringUTFChars(outputPath, nullptr);

    LOGI("Transcoding: %s -> %s", inPath, outPath);

    // Read the KTX2 file
    FILE* inFile = fopen(inPath, "rb");
    if (!inFile) {
        LOGE("Cannot open input file: %s", inPath);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    fseek(inFile, 0, SEEK_END);
    long fileSize = ftell(inFile);
    fseek(inFile, 0, SEEK_SET);

    if (fileSize <= 0) {
        LOGE("Input file is empty: %s", inPath);
        fclose(inFile);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    uint8_t* fileData = (uint8_t*)malloc(fileSize);
    if (!fileData) {
        LOGE("Cannot allocate %ld bytes for input file", fileSize);
        fclose(inFile);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    size_t bytesRead = fread(fileData, 1, fileSize, inFile);
    fclose(inFile);

    if ((long)bytesRead != fileSize) {
        LOGE("Short read: got %zu, expected %ld", bytesRead, fileSize);
        free(fileData);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    LOGI("Read %ld bytes from %s", fileSize, inPath);

    // Initialize KTX2 transcoder
    basist::ktx2_transcoder ktx2_tc;
    if (!ktx2_tc.init(fileData, (uint32_t)fileSize)) {
        LOGE("Failed to init KTX2 transcoder — not a valid KTX2 file?");
        free(fileData);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    uint32_t width = ktx2_tc.get_width();
    uint32_t height = ktx2_tc.get_height();
    uint32_t levels = ktx2_tc.get_levels();
    uint32_t layers = ktx2_tc.get_layers();
    uint32_t faces = ktx2_tc.get_faces();

    LOGI("KTX2: %ux%u, levels=%u, layers=%u, faces=%u, format=%u",
         width, height, levels, layers, faces, (uint32_t)ktx2_tc.get_basis_tex_format());

    // Start transcoding (decompresses ETC1S codebooks if needed)
    if (!ktx2_tc.start_transcoding()) {
        LOGE("Failed to start transcoding");
        free(fileData);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    // Open output file
    FILE* outFile = fopen(outPath, "wb");
    if (!outFile) {
        LOGE("Cannot open output file: %s", outPath);
        free(fileData);
        env->ReleaseStringUTFChars(inputPath, inPath);
        env->ReleaseStringUTFChars(outputPath, outPath);
        return JNI_FALSE;
    }

    // Write ASTC file header (16 bytes)
    // Format: magic(4) + blockX(1) + blockY(1) + blockZ(1) + dimX(3) + dimY(3) + dimZ(3)
    uint8_t astcHeader[16];
    astcHeader[0] = 0x13; astcHeader[1] = 0xAB; astcHeader[2] = 0xA1; astcHeader[3] = 0x5C; // magic
    astcHeader[4] = 4;  // blockX (4x4 ASTC)
    astcHeader[5] = 4;  // blockY
    astcHeader[6] = 1;  // blockZ
    astcHeader[7] = width & 0xFF;
    astcHeader[8] = (width >> 8) & 0xFF;
    astcHeader[9] = (width >> 16) & 0xFF;
    astcHeader[10] = height & 0xFF;
    astcHeader[11] = (height >> 8) & 0xFF;
    astcHeader[12] = (height >> 16) & 0xFF;
    astcHeader[13] = 1;  // dimZ
    astcHeader[14] = 0;
    astcHeader[15] = 0;
    fwrite(astcHeader, 1, 16, outFile);

    // Transcode each layer × face × mip level
    // For 2D textures: layers=0 (or 1), faces=1
    // For cubemaps: layers=0, faces=6
    // For texture arrays: layers=N, faces=1
    // We iterate all combinations so nothing gets silently dropped.
    uint32_t effectiveLayers = (layers == 0) ? 1 : layers;
    uint32_t effectiveFaces = (faces == 0) ? 1 : faces;
    uint32_t totalSlices = effectiveLayers * effectiveFaces;

    bool success = true;
    for (uint32_t level = 0; level < levels; level++) {
        uint32_t levelWidth = width >> level;
        uint32_t levelHeight = height >> level;
        if (levelWidth == 0) levelWidth = 1;
        if (levelHeight == 0) levelHeight = 1;

        uint32_t blocksX = (levelWidth + 3) / 4;
        uint32_t blocksY = (levelHeight + 3) / 4;
        uint32_t blocksPerSlice = blocksX * blocksY;
        uint32_t outputSizePerSlice = blocksPerSlice * 16;

        // For multi-slice textures, transcode each slice and write sequentially
        for (uint32_t layerIdx = 0; layerIdx < effectiveLayers; layerIdx++) {
            for (uint32_t faceIdx = 0; faceIdx < effectiveFaces; faceIdx++) {
                void* outputBuf = malloc(outputSizePerSlice);
                if (!outputBuf) {
                    LOGE("Cannot allocate %u bytes for ASTC output (level %u, layer %u, face %u)",
                         outputSizePerSlice, level, layerIdx, faceIdx);
                    success = false;
                    break;
                }

                bool result = ktx2_tc.transcode_image_level(
                    level,
                    layerIdx,
                    faceIdx,
                    outputBuf,
                    blocksPerSlice,
                    basist::transcoder_texture_format::cTFASTC_4x4_RGBA,
                    0
                );

                if (!result) {
                    LOGE("Transcode failed for level %u, layer %u, face %u",
                         level, layerIdx, faceIdx);
                    free(outputBuf);
                    success = false;
                    break;
                }

                size_t written = fwrite(outputBuf, 1, outputSizePerSlice, outFile);
                free(outputBuf);

                if (written != outputSizePerSlice) {
                    LOGE("Short write for level %u, layer %u, face %u: got %zu, expected %u",
                         level, layerIdx, faceIdx, written, outputSizePerSlice);
                    success = false;
                    break;
                }

                LOGI("Transcoded level %u, layer %u, face %u: %ux%u -> %u blocks (%u bytes)",
                     level, layerIdx, faceIdx, levelWidth, levelHeight,
                     blocksPerSlice, outputSizePerSlice);
            }
            if (!success) break;
        }
        if (!success) break;
    }

    fclose(outFile);
    free(fileData);

    if (success) {
        LOGI("Transcode complete: %s -> %s", inPath, outPath);
    } else {
        LOGE("Transcode failed");
        remove(outPath);
    }

    env->ReleaseStringUTFChars(inputPath, inPath);
    env->ReleaseStringUTFChars(outputPath, outPath);

    return success ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jboolean JNICALL
Java_com_winlator_core_AuroraTextureHelper_nativeIsKtx2File(
        JNIEnv* env, jclass cls, jstring filePath) {

    const char* path = env->GetStringUTFChars(filePath, nullptr);
    FILE* f = fopen(path, "rb");
    if (!f) {
        env->ReleaseStringUTFChars(filePath, path);
        return JNI_FALSE;
    }

    // KTX2 magic: 0xAB 0x4B 0x54 0x58 0x20 0x32 0x30 0xBB
    uint8_t magic[8];
    size_t read = fread(magic, 1, 8, f);
    fclose(f);
    env->ReleaseStringUTFChars(filePath, path);

    if (read != 8) return JNI_FALSE;

    static const uint8_t ktx2_magic[8] = {0xAB, 0x4B, 0x54, 0x58, 0x20, 0x32, 0x30, 0xBB};
    return (memcmp(magic, ktx2_magic, 8) == 0) ? JNI_TRUE : JNI_FALSE;
}

} // extern "C"
