package org.mehdimt.v2rayfinder.runtime.xray

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Debug-only adapter for the native Kotlin validation path.
 *
 * This class is intentionally not wired into MainActivity. It gives future debug
 * screens or instrumentation tests a single safe entry point for comparing the
 * Kotlin validator against the existing Python real-validation path.
 */
class NativeValidationDebugAdapter(
    private val validator: NativeXrayValidator = NativeXrayValidator(),
) {
    fun validateToJson(config: String, binaryPath: String, workDir: File): String {
        val built = XrayConfigBuilder.build(config)
            ?: return errorJson(config, "xray_config_build_failed")

        val result = validator.validate(
            config = config,
            xrayBinaryPath = binaryPath,
            xrayConfigJson = built.xrayConfigJson,
            workDir = workDir,
            socksPort = built.socksPort,
        )

        return result.toJsonObject(protocol = built.protocol, socksPort = built.socksPort).toString()
    }

    private fun NativeRealValidationResult.toJsonObject(protocol: String, socksPort: Int): JSONObject {
        val probes = JSONArray()
        for (probe in probeResults) {
            probes.put(
                JSONObject()
                    .put("name", probe.name)
                    .put("ok", probe.ok)
                    .put("status", probe.statusCode)
                    .put("latency_ms", probe.latencyMs ?: JSONObject.NULL)
                    .put("error", probe.error)
            )
        }
        return JSONObject()
            .put("engine", "kotlin_native_debug")
            .put("config", config)
            .put("protocol", protocol)
            .put("validation_ok", validationOk)
            .put("confidence_score", confidenceScore)
            .put("confidence_level", confidenceLevel)
            .put("passed_probes", passedProbes)
            .put("total_probes", totalProbes)
            .put("latency_ms", latencyMs ?: JSONObject.NULL)
            .put("socks_port", socksPort)
            .put("error", error)
            .put("probe_results", probes)
    }

    private fun errorJson(config: String, error: String): String = JSONObject()
        .put("engine", "kotlin_native_debug")
        .put("config", config)
        .put("validation_ok", false)
        .put("confidence_score", 0.0)
        .put("confidence_level", "none")
        .put("passed_probes", 0)
        .put("total_probes", NativeXrayValidator.DEFAULT_PROBES.size)
        .put("error", error)
        .put("probe_results", JSONArray())
        .toString()
}
