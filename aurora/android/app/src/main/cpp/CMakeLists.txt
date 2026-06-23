cmake_minimum_required(VERSION 3.22.1)

Project(Pluvia)

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -O2 -Wno-unused-function -Wimplicit-function-declaration")
set(CMAKE_SHARED_LINKER_FLAGS_RELEASE "${CMAKE_SHARED_LINKER_FLAGS_RELEASE} -s")

#add_subdirectory(proot)
add_subdirectory(virglrenderer)
add_subdirectory(patchelf)
add_subdirectory(extras/adrenotools)

add_library(winlator SHARED
            winlator/drawable.c
            winlator/sysvshared_memory.c
            winlator/xconnector_epoll.c
            winlator/alsa_client.c
            winlator/patchelf_wrapper.cpp)

target_link_libraries(winlator
                      log
                      android
                      jnigraphics
                      aaudio
                      EGL
                      GLESv2
                      GLESv3)

target_link_options(winlator PRIVATE -Wl,-z,max-page-size=16384)


add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/window_vert.h
    COMMAND glslangValidator -V --vn window_vert_code -x
            -o ${CMAKE_CURRENT_BINARY_DIR}/window_vert.h
            ${CMAKE_CURRENT_SOURCE_DIR}/winlator/window.vert
    DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/winlator/window.vert
)

add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/window_frag.h
    COMMAND glslangValidator -V --vn window_frag_code -x
            -o ${CMAKE_CURRENT_BINARY_DIR}/window_frag.h
            ${CMAKE_CURRENT_SOURCE_DIR}/winlator/window.frag
    DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/winlator/window.frag
)

add_library(vulkan_renderer SHARED
            winlator/vulkan_jni.cpp
            winlator/VulkanRendererContext.cpp
            winlator/VulkanRendererScanout.cpp
            ${CMAKE_CURRENT_BINARY_DIR}/window_vert.h
            ${CMAKE_CURRENT_BINARY_DIR}/window_frag.h)

target_include_directories(vulkan_renderer PRIVATE ${CMAKE_CURRENT_BINARY_DIR})

target_compile_options(vulkan_renderer PRIVATE
                       -Wall -Wextra -fvisibility=hidden -std=c++17)

target_link_libraries(vulkan_renderer
                      log
                      android
                      vulkan
                      adrenotools
                      dl
                      atomic)

target_link_options(vulkan_renderer PRIVATE -Wl,-z,max-page-size=16384)

# =============================================================================
# Aurora Mali Vulkan Sanitizer Layer
# =============================================================================
# A Vulkan layer that intercepts calls between DXVK and the Mali driver.
# Filters blacklisted extensions, splits large descriptor sets, etc.
#
# NOTE: This compiles with NDK (bionic). For production use inside the
# PRoot/glibc environment, it needs to be recompiled with a glibc
# cross-compiler. The resulting .so goes in imagefs/usr/lib/.
# =============================================================================
add_library(aurora_mali_sanitizer SHARED
            aurora_mali_sanitizer/aurora_mali_sanitizer.cpp)

target_compile_options(aurora_mali_sanitizer PRIVATE
                       -Wall -Wextra -fvisibility=hidden -std=c++17)

target_link_libraries(aurora_mali_sanitizer
                      log
                      vulkan
                      dl)

target_link_options(aurora_mali_sanitizer PRIVATE -Wl,-z,max-page-size=16384)

# =============================================================================
# Aurora Texture Engine (Phase 1)
# =============================================================================
# Basis Universal transcoder — converts KTX2/UASTC to ASTC on-device.
# Single-file library, no external dependencies.
# =============================================================================
add_library(aurora_texture SHARED
            aurora_texture/aurora_texture_jni.cpp
            aurora_texture/basisu_transcoder.cpp)

target_include_directories(aurora_texture PRIVATE
                           aurora_texture)

target_compile_options(aurora_texture PRIVATE
                       -Wall -fvisibility=hidden -std=c++17 -O2)

target_link_libraries(aurora_texture
                      log
                      dl)

target_link_options(aurora_texture PRIVATE -Wl,-z,max-page-size=16384)

# =============================================================================
# Aurora Mesh Engine (Phase 2)
# meshoptimizer — QEM mesh simplification (Garland & Heckbert 1997)
# MIT licensed (Arseny Kapoulkine)
# =============================================================================
add_library(aurora_mesh SHARED
            aurora_mesh/aurora_mesh_jni.cpp
            aurora_mesh/simplifier.cpp
            aurora_mesh/allocator.cpp
            aurora_mesh/indexgenerator.cpp
            aurora_mesh/vfetchoptimizer.cpp)

target_include_directories(aurora_mesh PRIVATE aurora_mesh)
target_compile_options(aurora_mesh PRIVATE -Wall -fvisibility=hidden -std=c++17 -O2)
target_link_libraries(aurora_mesh log dl)
target_link_options(aurora_mesh PRIVATE -Wl,-z,max-page-size=16384)
