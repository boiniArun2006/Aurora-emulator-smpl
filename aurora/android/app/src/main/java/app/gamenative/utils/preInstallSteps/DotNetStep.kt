package app.gamenative.utils

import app.gamenative.data.GameSource
import app.gamenative.enums.Marker
import com.winlator.container.Container
import java.io.File
import timber.log.Timber

/**
 * Aurora Phase 7a: .NET Framework auto-installer.
 *
 * Scans the game directory for .NET Framework installers and queues
 * them for silent installation. Required by many C# games and tools.
 *
 * Aurora-specific addition (not in GameNative).
 */
object DotNetStep : PreInstallStep {
    override val marker: Marker = Marker.DOTNET_INSTALLED

    override fun appliesTo(
        container: Container,
        gameSource: GameSource,
        gameDirPath: String,
    ): Boolean {
        return !MarkerUtils.hasMarker(gameDirPath, Marker.DOTNET_INSTALLED)
    }

    override fun buildCommand(
        container: Container,
        appId: String,
        gameSource: GameSource,
        gameDir: File,
        gameDirPath: String,
    ): String? {
        val searchDirs = listOf(
            File(gameDirPath, "_CommonRedist"),
            File(gameDirPath, "_CommonRedist/DotNet"),
            File(gameDirPath, "_CommonRedist/.NET"),
            File(gameDirPath, "redist"),
            File(gameDirPath, "Redist"),
            File(gameDirPath, "Prerequisites"),
        ).filter { it.exists() && it.isDirectory }

        if (searchDirs.isEmpty()) {
            Timber.tag("DotNetStep").i("No .NET search directories found")
            return null
        }

        val parts = mutableListOf<String>()

        // .NET installer name patterns
        val dotnetPatterns = listOf(
            Regex("(?i)dotnetfx.*\\.exe"),
            Regex("(?i)NDP.*\\.exe"),
            Regex("(?i)\\.net.*framework.*\\.exe"),
        )

        for (dir in searchDirs) {
            Timber.tag("DotNetStep").i("Searching for .NET installers under ${dir.absolutePath}")
            dir.walkTopDown()
                .filter { file ->
                    file.isFile && file.extension.equals("exe", ignoreCase = true) &&
                        dotnetPatterns.any { it.matches(file.name) }
                }
                .forEach { installerFile ->
                    val relativePath = installerFile
                        .relativeTo(gameDir)
                        .path
                        .replace('/', '\\')
                    val winePath = "A:\\$relativePath"
                    Timber.tag("DotNetStep").i("Queued .NET installer: $winePath")
                    parts.add("$winePath /q /norestart")
                }
        }

        return if (parts.isEmpty()) null else parts.joinToString(" & ")
    }
}
