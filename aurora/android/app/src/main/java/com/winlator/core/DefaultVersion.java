package com.winlator.core;

import static com.winlator.container.Container.STEAM_TYPE_NORMAL;

import com.winlator.container.Container;

/**
 * Compile-time fallback version constants for Aurora components.
 *
 * These are used when the ContentsManager remote manifest hasn't been
 * loaded yet (first launch, offline). At runtime, ContentsManager
 * .getLatestVersionName() should be preferred for selecting the newest
 * available version from the merged local+remote profile list.
 *
 * Versions checked 2026-06-23 against:
 * - WinNative-Components manifest: https://github.com/nicholasx417/WinNative-Components
 * - proton-wine releases: https://github.com/WinNative-Emu/proton-wine/releases
 * - Box64 releases: https://github.com/ptitSeb/box64/releases
 * - DXVK releases: https://github.com/doitsujin/dxvk/releases
 *
 * These constants go stale silently — re-check before bumping.
 */
public abstract class DefaultVersion {

    // Box64: checked 2026-06-23 (latest stable: 0.4.3, Aurora uses 0.4.2)
    public static final String BOX86 = "0.3.2";
    public static final String BOX64 = "0.4.2";

    // FEXCore: checked 2026-06-23 (latest: 2605)
    public static final String FEXCORE = "2605";

    // GPU drivers: checked 2026-06-23
    public static String WRAPPER = "System";
    public static final String TURNIP = "25.2.0";
    public static final String ZINK = "22.2.5";
    public static final String VIRGL = "23.1.9";
    public static final String VORTEK = "2.1-22.2.5";
    public static final String ADRENO = "819.2";
    public static final String SD8ELITE = "800.51";

    // DXVK: checked 2026-06-23 (latest stable: 2.6.1-gplasync)
    public static String DXVK = "2.6.1-gplasync";

    // D8VK: checked 2026-06-23
    public static final String D8VK = "1.0";

    // VKD3D: checked 2026-06-23 (latest: 3.0.1 in WinNative manifest)
    // Aurora uses 2.14.1 as fallback (matches GameNative baseline)
    public static String VKD3D = "2.14.1";

    public static final String CNC_DDRAW = "6.6";
    public static String STEAM_TYPE = STEAM_TYPE_NORMAL;
    public static String VARIANT = Container.GLIBC;
    public static String DEFAULT_GRAPHICS_DRIVER = "vortek";

    // Wine/Proton: checked 2026-06-23
    // Aligned with WinNative-Emu/WinNative's WineInfo.MAIN_WINE_VERSION
    // Source: https://github.com/WinNative-Emu/WinNative/blob/main/.../WineInfo.java
    // Proton 11.0 is in beta (beta 5, 2026-05-29) — not stable enough yet
    public static String WINE_VERSION = com.winlator.core.WineInfo.MAIN_WINE_VERSION.identifier();

    public static String ASYNC = "1";
    public static String ASYNC_CACHE = "0";
}
