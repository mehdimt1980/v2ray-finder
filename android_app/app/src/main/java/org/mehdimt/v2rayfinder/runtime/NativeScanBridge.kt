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
    fun scan(context: Context, limit: Int, timeoutSeconds: Double, health: Boolean, token: String): String =
        scan(context, limit, timeoutSeconds, health, false, token)

    @JvmStatic
    fun scan(context: Context, limit: Int, timeoutSeconds: Double, health: Boolean, realValidation: Boolean, token: String): String {
        val maxConfigs = if (limit > 0) limit else 200
        val timeoutMs = (timeoutSeconds.coerceAtLeast(1.0) * 1000.0).toInt()
        val sources = loadSources(context)
        val parsed = NativeFetchParseEngine(SourceFetcher(timeoutMs, timeoutMs)).run(sources, 50)
        val attribution = buildAttribution(parsed)
        val configs = selectBalancedConfigs(parsed, maxConfigs)
        val checks = if (health) TcpHealthChecker(timeoutMs).checkAll(configs, maxConfigs) else configs.map { TcpHealthResult(it, EndpointParser.parse(it), true, null, "") }
        val tcpScored = NativeScoringEngine.score(checks)
        val xrayReport = if (realValidation) runXrayValidation(context, tcpScored) else XrayReport(emptyMap(), emptyMap(), if (isXrayBinaryAvailable(context)) "disabled" else "missing_binary")
        val ranked = tcpScored.map { item -> RankedItem(item, xrayReport.results[item.config], scoreWithXray(item.score, xrayReport.results[item.config])) }
            .sortedWith(compareByDescending<RankedItem> { it.finalScore }.thenBy { it.base.latencyMs ?: Long.MAX_VALUE })

        val configArray = JSONArray()
        val items = JSONArray()
        for (rankedItem in ranked) {
            val item = rankedItem.base
            configArray.put(item.config)
            val sourcesForConfig = attribution[item.config].orEmpty()
            val primary = sourcesForConfig.firstOrNull()
            val sourceLabels = JSONArray()
            val sourceUrls = JSONArray()
            for (src in sourcesForConfig) {
                sourceLabels.put(src.label)
                sourceUrls.put(src.url)
            }
            val xray = rankedItem.xray
            items.put(JSONObject()
                .put("config", item.config)
                .put("protocol", item.protocol)
                .put("grade", grade(rankedItem.finalScore))
                .put("total", rankedItem.finalScore)
                .put("tcp_score", item.score)
                .put("latency_ms", xray?.latencyMs ?: item.latencyMs ?: JSONObject.NULL)
                .put("source", primary?.url ?: "")
                .put("source_label", primary?.label ?: "")
                .put("source_count", sourcesForConfig.size)
                .put("source_labels", sourceLabels)
                .put("source_urls", sourceUrls)
                .put("xray_requested", realValidation)
                .put("xray_checked", xray != null)
                .put("xray_ok", xray?.validationOk ?: false)
                .put("xray_confidence", xray?.confidenceScore ?: JSONObject.NULL)
                .put("xray_confidence_level", xray?.confidenceLevel ?: "")
                .put("xray_passed_probes", xray?.passedProbes ?: 0)
                .put("xray_total_probes", xray?.totalProbes ?: 0)
                .put("xray_error", xray?.error ?: "")
                .put("xray_skip_reason", xrayReport.skipped[item.config] ?: ""))
        }

        val performance = JSONArray()
        for (sourceResult in parsed.sourceResults) {
            val sourceUrl = sourceResult.source.url
            val xrayForSource = xrayReport.results.filter { attribution[it.key].orEmpty().any { src -> src.url == sourceUrl } }.values
            performance.put(JSONObject()
                .put("label", sourceResult.source.label)
                .put("url", sourceUrl)
                .put("fetch_ok", sourceResult.fetchResult.ok)
                .put("source_score", if (sourceResult.ok) 50.0 else 0.0)
                .put("tcp_ok_count", checks.count { attribution[it.config].orEmpty().any { src -> src.url == sourceUrl } && it.reachable })
                .put("tcp_candidates", sourceResult.uniqueConfigCount)
                .put("selected_count", configs.count { cfg -> attribution[cfg].orEmpty().any { src -> src.url == sourceUrl } })
                .put("xray_ok_count", xrayForSource.count { it.validationOk })
                .put("xray_checked_count", xrayForSource.count())
                .put("trust", sourceResult.source.trust))
        }

        return JSONObject()
            .put("stats", JSONObject()
                .put("fetched", parsed.rawConfigCount)
                .put("deduped", configs.size)
                .put("healthy", tcpScored.count { it.reachable })
                .put("scored", ranked.size)
                .put("sources_checked", parsed.sourcesChecked)
                .put("sources_ok", parsed.sourcesOk)
                .put("xray_requested", realValidation)
                .put("xray_status", xrayReport.status)
                .put("xray_checked", xrayReport.results.size)
                .put("xray_ok", xrayReport.results.values.count { it.validationOk })
                .put("xray_skipped", xrayReport.skipped.size))
            .put("configs", configArray)
            .put("items", items)
            .put("failed_sources", failedSources(parsed))
            .put("source_performance", performance)
            .toString()
    }

    private fun buildAttribution(parsed: NativeFetchParseResult): Map<String, List<SourceRecord>> {
        val out = linkedMapOf<String, MutableList<SourceRecord>>()
        for (sourceResult in parsed.sourceResults) {
            for (config in sourceResult.configs) {
                val list = out.getOrPut(config) { mutableListOf() }
                if (list.none { it.url == sourceResult.source.url }) list += sourceResult.source
            }
        }
        return out
    }

    private fun selectBalancedConfigs(parsed: NativeFetchParseResult, limit: Int): List<String> {
        val perSource = parsed.sourceResults
            .filter { it.configs.isNotEmpty() }
            .map { it.configs.toMutableList() }
            .toMutableList()
        val selected = mutableListOf<String>()
        val seen = linkedSetOf<String>()
        while (selected.size < limit && perSource.any { it.isNotEmpty() }) {
            for (bucket in perSource) {
                while (bucket.isNotEmpty()) {
                    val config = bucket.removeAt(0)
                    if (seen.add(config)) {
                        selected += config
                        break
                    }
                }
                if (selected.size >= limit) break
            }
        }
        return selected
    }

    private fun runXrayValidation(context: Context, scored: List<ScoredConfig>): XrayReport {
        val binary = File(context.applicationInfo.nativeLibraryDir ?: "", "libxray.so")
        if (!binary.isFile) return XrayReport(emptyMap(), scored.associate { it.config to "xray_binary_missing" }, "missing_binary")
        val workDir = File(context.filesDir, "native-xray-validation")
        if (!workDir.exists()) workDir.mkdirs()
        val validator = NativeXrayValidator()
        val out = linkedMapOf<String, NativeRealValidationResult>()
        val skipped = linkedMapOf<String, String>()
        val candidates = scored.filter { it.reachable }.take(XRAY_VALIDATION_LIMIT)
        for (item in candidates) {
            val built = XrayConfigBuilder.build(item.config)
            if (built == null) {
                skipped[item.config] = "xray_config_build_failed"
                continue
            }
            out[item.config] = validator.validate(item.config, binary.absolutePath, built.xrayConfigJson, workDir, built.socksPort)
        }
        for (item in scored.filter { !it.reachable }.take(XRAY_VALIDATION_LIMIT)) skipped[item.config] = "tcp_unreachable"
        return XrayReport(out, skipped, "active")
    }

    private fun isXrayBinaryAvailable(context: Context): Boolean = File(context.applicationInfo.nativeLibraryDir ?: "", "libxray.so").isFile
    private fun scoreWithXray(baseScore: Double, xray: NativeRealValidationResult?): Double = if (xray == null) baseScore else if (xray.validationOk) maxOf(baseScore, 78.0 + xray.confidenceScore * 22.0).coerceIn(0.0, 100.0) else (baseScore * 0.35).coerceIn(0.0, 100.0)
    private fun grade(score: Double): String = when { score >= 90.0 -> "A+"; score >= 80.0 -> "A"; score >= 70.0 -> "B"; score >= 60.0 -> "C"; score >= 45.0 -> "D"; else -> "F" }
    private fun loadSources(context: Context): List<SourceRecord> { val registry = BundledSourceRegistry(context); val cached = NativeSourceRefreshBridge.cachedRegistryFile(context); return if (cached.isFile) registry.loadFromFile(cached) else registry.loadFromAssets("sources.json") }
    private fun failedSources(parsed: NativeFetchParseResult): JSONArray { val out = JSONArray(); for (sourceResult in parsed.sourceResults) if (!sourceResult.ok) out.put(JSONObject().put("url", sourceResult.source.url).put("label", sourceResult.source.label).put("message", sourceResult.fetchResult.error.ifBlank { "no configs extracted" }).put("status_code", sourceResult.fetchResult.statusCode)); return out }
    private data class RankedItem(val base: ScoredConfig, val xray: NativeRealValidationResult?, val finalScore: Double)
    private data class XrayReport(val results: Map<String, NativeRealValidationResult>, val skipped: Map<String, String>, val status: String)
}
