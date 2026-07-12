package org.mehdimt.v2rayfinder.runtime.xray

import java.io.File

/**
 * Native xray validation orchestration for Phase 5.
 *
 * This layer starts xray with a caller-provided config JSON, probes through the
 * local SOCKS inbound, then always stops the process and deletes the temporary
 * config file. It is not wired into the active UI scan path yet.
 */
class NativeXrayValidator(
    private val processRunner: XrayProcessRunner = XrayProcessRunner(),
    private val probeRunner: HttpProbeRunner = HttpProbeRunner(),
) {
    fun validate(
        config: String,
        xrayBinaryPath: String,
        xrayConfigJson: String,
        workDir: File,
        socksPort: Int = PortUtils.findFreePort(),
        probes: List<ProbeEndpoint> = DEFAULT_PROBES,
    ): NativeRealValidationResult {
        var handle: XrayProcessHandle? = null
        return try {
            val processConfig = XrayProcessConfig(
                binaryPath = xrayBinaryPath,
                configJson = xrayConfigJson,
                workDir = workDir,
                socksPort = socksPort,
            )
            handle = processRunner.start(processConfig)
            val probeResults = probeRunner.runAll(probes, handle.socksHost, handle.socksPort)
            buildResult(config, probeResults)
        } catch (exc: Exception) {
            NativeRealValidationResult(
                config = config,
                validationOk = false,
                confidenceScore = 0.0,
                confidenceLevel = "none",
                passedProbes = 0,
                totalProbes = probes.size,
                error = exc.message ?: exc.javaClass.simpleName,
            )
        } finally {
            handle?.stop()
        }
    }

    private fun buildResult(config: String, probeResults: List<ProbeResult>): NativeRealValidationResult {
        val total = probeResults.size
        val passed = probeResults.count { it.ok }
        val bestLatency = probeResults.mapNotNull { it.latencyMs }.minOrNull()
        val successRatio = if (total == 0) 0.0 else passed.toDouble() / total.toDouble()
        val latencyScore = when {
            bestLatency == null -> 0.0
            bestLatency <= 800L -> 0.15
            bestLatency <= 1_800L -> 0.10
            else -> 0.05
        }
        val confidence = (successRatio * 0.85 + latencyScore).coerceIn(0.0, 1.0)
        val ok = passed >= 1 && confidence >= 0.40
        return NativeRealValidationResult(
            config = config,
            validationOk = ok,
            confidenceScore = confidence,
            confidenceLevel = confidenceLevel(confidence),
            passedProbes = passed,
            totalProbes = total,
            latencyMs = bestLatency,
            error = if (ok) "" else probeResults.firstOrNull { !it.ok }?.error.orEmpty(),
            probeResults = probeResults,
        )
    }

    private fun confidenceLevel(score: Double): String = when {
        score >= 0.85 -> "high"
        score >= 0.60 -> "medium"
        score >= 0.40 -> "low"
        else -> "none"
    }

    companion object {
        val DEFAULT_PROBES: List<ProbeEndpoint> = listOf(
            ProbeEndpoint("cloudflare_trace", "https://one.one.one.one/cdn-cgi/trace", 200, 399),
            ProbeEndpoint("google_204", "https://clients3.google.com/generate_204", 204, 204),
        )
    }
}
