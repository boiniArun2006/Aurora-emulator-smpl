package app.gamenative.utils

import app.gamenative.data.GameSource
import app.gamenative.enums.Marker
import com.winlator.container.Container
import java.io.File
import timber.log.Timber

/**
 * Aurora Phase 7a: DirectX Runtime auto-installer.
 *
 * Scans the game directory for DirectX installers (DXSETUP.exe) and
 * queues them for silent installation. Required by most pre-2015 games.
 *
 * Aurora-specific addition (not in GameNative).
 */
object DirectXStep : PreInstallStep {
    override val marker: Marker = Marker.DIRECTX_INSTALLED

    override fun appliesTo(
        container: Container,
        gameSource: GameSource,
        gameDirPath: String,
    ): Boolean {
        return !MarkerUtils.hasMarker(gameDirPath, Marker.DIRECTX_INSTALLED)
    }

    override fun buildCommand(
        container: Container,
        appId: String,
        gameSource: GameSource,
        gameDir: File,
        gameDirPath: String,
    ): String? {
        val searchDirs = listOf(
            File(gameDirPath, "_CommonRedist/DirectX"),
            File(gameDirPath, "DirectX"),
            File(gameDirPath, "Redist/DirectX"),
            File(gameDirPath, "__Installer/directx"),
            File(gameDirPath, "__Installer/directx/redist"),
            File(gameDirPath, "redist"),
            File(gameDirPath, "Redist"),
        ).filter { it.exists() && it.isDirectory }

        if (searchDirs.isEmpty()) {
            Timber.tag("DirectXStep").i("No DirectX search directories found")
            return null
        }

        val parts = mutableListOf<String>()

        for (dir in searchDirs) {
            Timber.tag("DirectXStep").i("Searching for DXSETUP.exe under ${dir.absolutePath}")
            dir.walkTopDown()
                .filter { file ->
                    file.isFile &&
                        file.name.equals("DXSETUP.exe", ignoreCase = true)
                }
                .forEach { installerFile ->
                    val relativePath = installerFile
                        .relativeTo(gameDir)
                        .path
                        .replace('/', '\\')
                    val winePath = "A:\\$relativePath"
                    Timber.tag("DirectXStep").i("Queued DirectX installer: $winePath")
                    parts.add("$winePath /silent")
                }
        }

        return if (parts.isEmpty()) null else parts.joinToString(" & ")
    }
}
