package org.mehdimt.v2rayfinder.runtime.xray

import java.io.File

/** Configuration needed to start one native xray validation process. */
data class XrayProcessConfig(
    val binaryPath: String,
    val configJson: String,
    val workDir: File,
    val socksHost: String = "127.0.0.1",
    val socksPort: Int,
    val startupTimeoutMs: Long = 5_000L,
) {
    val isUsable: Boolean
        get() = binaryPath.isNotBlank() && configJson.isNotBlank() && socksPort in 1..65535
}

/** Running xray process plus the generated temporary config file. */
data class XrayProcessHandle(
    val process: Process,
    val configFile: File,
    val socksHost: String,
    val socksPort: Int,
) {
    fun stop() {
        try {
            process.destroy()
            if (process.isAlive) process.destroyForcibly()
        } catch (_: Exception) {
        }
        try {
            configFile.delete()
        } catch (_: Exception) {
        }
    }
}
