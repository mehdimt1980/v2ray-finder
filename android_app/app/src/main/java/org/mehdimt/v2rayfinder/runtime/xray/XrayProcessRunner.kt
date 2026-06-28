package org.mehdimt.v2rayfinder.runtime.xray

import java.io.File

/** Starts and stops a bundled xray process for native validation. */
class XrayProcessRunner {
    fun start(config: XrayProcessConfig): XrayProcessHandle {
        require(config.isUsable) { "Invalid xray process configuration" }

        if (!config.workDir.exists()) config.workDir.mkdirs()
        val binary = File(config.binaryPath)
        require(binary.isFile) { "xray binary not found: ${config.binaryPath}" }
        binary.setExecutable(true)

        val configFile = File.createTempFile("xray-validation-", ".json", config.workDir)
        configFile.writeText(config.configJson, Charsets.UTF_8)

        val process = ProcessBuilder(binary.absolutePath, "run", "-config", configFile.absolutePath)
            .directory(config.workDir)
            .redirectErrorStream(true)
            .start()

        val handle = XrayProcessHandle(
            process = process,
            configFile = configFile,
            socksHost = config.socksHost,
            socksPort = config.socksPort,
        )

        val ready = PortUtils.waitForPort(config.socksHost, config.socksPort, config.startupTimeoutMs)
        if (!ready || !process.isAlive) {
            handle.stop()
            throw IllegalStateException("xray did not open SOCKS port ${config.socksHost}:${config.socksPort}")
        }

        return handle
    }
}
