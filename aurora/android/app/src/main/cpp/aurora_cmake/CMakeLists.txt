# Aurora Emulator - Native Libraries Build
# ============================================
# Builds ONLY Aurora's native libraries (not GameNative's full native code).
# GameNative's .so files are pre-built and in jniLibs/.
#
# This CMake builds:
# 1. libaurora_mali_sanitizer.so — Vulkan layer for Mali driver bug workarounds
# 2. libaurora_texture.so — Basis Universal KTX2->ASTC texture transcoding
# 3. libaurora_mesh.so — meshoptimizer QEM mesh simplification
#
# All three are JNI bridges called from Java/Kotlin code.

cmake_minimum_required(VERSION 3.22.1)
project(aurora_native CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O2 -Wall -fvisibility=hidden -DBASISD_SUPPORT_KTX2_ZSTD=0")

# =============================================================================
# 1. Aurora Mali Vulkan Sanitizer Layer
# =============================================================================
add_library(aurora_mali_sanitizer SHARED
            ../aurora_mali_sanitizer/aurora_mali_sanitizer.cpp)

target_link_libraries(aurora_mali_sanitizer
                      log
                      vulkan
                      dl)

target_link_options(aurora_mali_sanitizer PRIVATE -Wl,-z,max-page-size=16384)

# =============================================================================
# 2. Aurora Texture Engine (Basis Universal transcoder)
# =============================================================================
add_library(aurora_texture SHARED
            ../aurora_texture/aurora_texture_jni.cpp
            ../aurora_texture/basisu_transcoder.cpp)

target_include_directories(aurora_texture PRIVATE
                           ../aurora_texture)

target_link_libraries(aurora_texture
                      log
                      dl)

target_link_options(aurora_texture PRIVATE -Wl,-z,max-page-size=16384)

# =============================================================================
# 3. Aurora Mesh Engine (meshoptimizer)
# =============================================================================
add_library(aurora_mesh SHARED
            ../aurora_mesh/aurora_mesh_jni.cpp
            ../aurora_mesh/simplifier.cpp
            ../aurora_mesh/allocator.cpp
            ../aurora_mesh/indexgenerator.cpp
            ../aurora_mesh/vfetchoptimizer.cpp)

target_include_directories(aurora_mesh PRIVATE
                           ../aurora_mesh)

target_link_libraries(aurora_mesh
                      log
                      dl)

target_link_options(aurora_mesh PRIVATE -Wl,-z,max-page-size=16384)
