package org.mehdimt.v2rayfinder.runtime

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import org.mehdimt.v2rayfinder.registry.BundledSourceRegistry
import org.mehdimt.v2rayfinder.registry.NativeSourceRefreshBridge
import org.mehdimt.v2rayfinder.registry.SourceRecord
import org.mehdimt.v2rayfinder.runtime.xray.NativeRealValidationResult
import org.mehdimt.v2rayfinder.runtime.xray.NativeXrayValidator
import org.mehdimt.v2rayfinder.runtime.xray.XrayConfigBuilder
import java.io.File

object NativeScanBridge {
    private const val XRAY_VALIDATION_LIMIT: Int = 50

    @JvmStatic
    fun scan(context: Context, limit: Int, timeoutSeconds: Double, health: Boolean, token: String): String {
        return scan(context, limit, timeoutSeconds, health, false, token)
    }

    @JvmStatic
    fun scan(context: Context, limit: Int, timeoutSeconds: Double, health: Boolean, realValidation: Boolean, token: String): String {
        val maxConfigs = if (limit > 0) limit else 200
        val timeoutMs = (timeoutSeconds.coerceAtLeast(1.0) * 1000.0).toInt()
        val sources = loadSources(context)
        val parsed = NativeFetchParseEngine(SourceFetcher(timeoutMs, timeoutMs)).run(sources, 50)
        val sourceByConfig = linkedMapOf<String, SourceRecord>()
        for (sourceResult in parsed.sourceResults) {
            for (config in sourceResult.configs) {
                if (!sourceByConfig.containsKey(config)) sourceByConfig[config] = sourceResult.source
            }
        }

        val configs = parsed.configs.take(maxConfigs)
        val checks = if (health) {
            TcpHealthChecker(timeoutMs).checkAll(configs, maxConfigs)
        } else {
            configs.map { TcpHealthResult(it, EndpointParser.parse(it), true, null, "") }
        }
        val scored = NativeScoringEngine.score(checks)
        val xrayResults = if (realValidation) runXrayValidation(context, scored) else emptyMap()

        val configArray = JSONArray()
        val items = JSONArray()
        for (config in configs) configArray.put(config)
        for (item in scored) {
            val source = sourceByConfig[item.config]
            val sourceUrl = source?.url ?: ""
            val sourceLabel = source?.label ?: ""
            val xray = xrayResults[item.config]
            val finalScore = scoreWithXray(item.score, xray)
            items.put(JSONObject()
                .put("config", item.config)
                .put("protocol", item.protocol)
                .put("grade", grade(finalScore))
                .put("total", finalScore)
                .put("latency_ms", xray?.latencyMs ?: item.latencyMs ?: JSONObject.NULL)
                .put("source", sourceUrl)
                .put("source_label", sourceLabel)
                .put("xray_checked", xray != null)
                .put("xray_ok", xray?.validationOk ?: false)
                .put("xray_confidence", xray?.confidenceScore ?: JSONObject.NULL)
                .put("xray_confidence_level", xray?.confidenceLevel ?: "")
                .put("xray_passed_probes", xray?.passedProbes ?: 0)
                .put("xray_total_probes", xray?.totalProbes ?: 0)
                .put("xray_error", xray?.error ?: ""))
        }

        val performance = JSONArray()
        for (sourceResult in parsed.sourceResults) {
            val sourceUrl = sourceResult.source.url
            val xrayForSource = xrayResults.filter { sourceByConfig[it.key]?.url == sourceUrl }.values
            performance.put(JSONObject()
                .put("label", sourceResult.source.label)
                .put("url", sourceUrl)
                .put("fetch_ok", sourceResult.fetchResult.ok)
                .put("source_score", if (sourceResult.ok) 50.0 else 0.0)
                .put("tcp_ok_count", checks.count { sourceByConfig[it.config]?.url == sourceUrl && it.reachable })
                .put("tcp_candidates", sourceResult.uniqueConfigCount)
                .put("xray_ok_count", xrayForSource.count { it.validationOk })
                .put("xray_checked_count", xrayForSource.count())
                .put("trust", sourceResult.source.trust))
        }

        return JSONObject()
            .put("stats", JSONObject()
                .put("fetched", parsed.rawConfigCount)
                .put("deduped", configs.size)
                .put("healthy", scored.count { it.reachable })
                .put("scored", scored.size)
                .put("xray_checked", xrayResults.size)
                .put("xray_ok", xrayResults.values.count { it.validationOk }))
            .put("configs", configArray)
            .put("items", items)
            .put("failed_sources", failedSources(parsed))
            .put("source_performance", performance)
            .toString()
    }

    private fun runXrayValidation(context: Context, scored: List<ScoredConfig>): Map<String, NativeRealValidationResult> {
        val binary = File(context.applicationInfo.nativeLibraryDir ?: "", "libxray.so")
        if (!binary.isFile) return emptyMap()
        val workDir = File(context.filesDir, "native-xray-validation")
        if (!workDir.exists()) workDir.mkdirs()
        val validator = NativeXrayValidator()
        val out = linkedMapOf<String, NativeRealValidationResult>()
        val candidates = scored.filter { it.reachable }.take(XRAY_VALIDATION_LIMIT)
        for (item in candidates) {
            val built = XrayConfigBuilder.build(item.config) ?: continue
            val result = validator.validate(
                config = item.config,
                xrayBinaryPath = binary.absolutePath,
                xrayConfigJson = built.xrayConfigJson,
                workDir = workDir,
                socksPort = built.socksPort,
            )
            out[item.config] = result
        }
        return out
    }

    private fun scoreWithXray(baseScore: Double, xray: NativeRealValidationResult?): Double {
        if (xray == null) return baseScore
        return if (xray.validationOk) {
            maxOf(baseScore, 78.0 + xray.confidenceScore * 22.0).coerceIn(0.0, 100.0)
        } else {
            (baseScore * 0.35).coerceIn(0.0, 100.0)
        }
    }

    private fun grade(score: Double): String = when {
        score >= 90.0 -> "A+"
        score >= 80.0 -> "A"
        score >= 70.0 -> "B"
        score >= 60.0 -> "C"
        score >= 45.0 -> "D"
        else -> "F"
    }

    private fun loadSources(context: Context): List<SourceRecord> {
        val registry = BundledSourceRegistry(context)
        val cached = NativeSourceRefreshBridge.cachedRegistryFile(context)
        return if (cached.isFile) registry.loadFromFile(cached) else registry.loadFromAssets("sources.json")
    }

    private fun failedSources(parsed: NativeFetchParseResult): JSONArray {
        val out = JSONArray()
        for (sourceResult in parsed.sourceResults) {
            if (!sourceResult.ok) {
                out.put(JSONObject()
                    .put("url", sourceResult.source.url)
                    .put("label", sourceResult.source.label)
                    .put("message", sourceResult.fetchResult.error.ifBlank { "no configs extracted" })
                    .put("status_code", sourceResult.fetchResult.statusCode))
            }
        }
        return out
    }
}
