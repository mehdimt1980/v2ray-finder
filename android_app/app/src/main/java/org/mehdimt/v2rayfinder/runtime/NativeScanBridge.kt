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
    @JvmStatic
    fun scan(context: Context, limit: Int, timeoutSeconds: Double, health: Boolean, token: String): String =
        scan(context, limit, timeoutSeconds, health, false, token)

    @JvmStatic
    fun scan(context: Context, limit: Int, timeoutSeconds: Double, health: Boolean, realValidation: Boolean, token: String): String {
        val maxConfigs = if (limit > 0) limit else 200
        val timeoutMs = (timeoutSeconds.coerceAtLeast(1.0) * 1000.0).toInt()
        val sources = loadSources(context)
        val parsed = NativeFetchParseEngine(SourceFetcher(timeoutMs, timeoutMs)).run(sources, 50)
        val selection = CandidateSelector.select(parsed, maxConfigs, realValidation)
        val attribution = selection.attribution
        val configs = selection.configs
        val checks = if (health) {
            TcpHealthChecker(timeoutMs).checkAll(configs, configs.size)
        } else {
            configs.map { TcpHealthResult(it, EndpointParser.parse(it), true, null, "") }
        }
        val tcpScored = NativeScoringEngine.score(checks)
        val xrayReport = if (realValidation) runXrayValidation(context, tcpScored, selection.xrayBudget) else XrayReport(emptyMap(), emptyMap(), if (isXrayBinaryAvailable(context)) "disabled" else "missing_binary")

        val ranked = tcpScored.map { item ->
            val xray = xrayReport.results[item.config]
            RankedItem(item, xray, scoreWithXray(item.score, xray))
        }.sortedWith(compareByDescending<RankedItem> { it.finalScore }.thenBy { it.base.latencyMs ?: Long.MAX_VALUE }).take(maxConfigs)

        val statusMessage = when {
            !realValidation -> "tcp_mode"
            xrayReport.status == "missing_binary" -> "xray_missing_binary"
            xrayReport.results.isEmpty() -> "xray_no_candidates_validated"
            xrayReport.results.values.none { it.validationOk } -> "xray_checked_but_none_passed_tcp_results_shown"
            else -> "xray_strict_ok"
        }

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
            val validation = validationLabel(item, xray, realValidation, xrayReport.skipped[item.config])
            val displaySourceLabel = listOfNotNull(primary?.label?.takeIf { it.isNotBlank() }, validation).joinToString(" | ")
            items.put(JSONObject()
                .put("config", item.config)
                .put("protocol", item.protocol)
                .put("grade", grade(rankedItem.finalScore))
                .put("total", rankedItem.finalScore)
                .put("tcp_checked", health)
                .put("tcp_ok", item.reachable)
                .put("tcp_latency_ms", item.latencyMs ?: JSONObject.NULL)
                .put("tcp_score", item.score)
                .put("latency_ms", xray?.latencyMs ?: item.latencyMs ?: JSONObject.NULL)
                .put("source", primary?.url ?: "")
                .put("source_label", displaySourceLabel)
                .put("source_count", sourcesForConfig.size)
                .put("source_labels", sourceLabels)
                .put("source_urls", sourceUrls)
                .put("validation_label", validation)
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
        performance.put(JSONObject()
            .put("label", "SMART SCAN — raw=${selection.rawConfigCount} — unique=${selection.uniqueConfigCount} — candidates=${selection.selectedCount}/${selection.candidateBudget} — xrayBudget=${selection.xrayBudget}")
            .put("url", "native://smart-candidate-selector")
            .put("fetch_ok", true)
            .put("source_score", 100.0)
            .put("tcp_ok_count", tcpScored.count { it.reachable })
            .put("tcp_candidates", tcpScored.size)
            .put("selected_count", ranked.size)
            .put("xray_ok_count", xrayReport.results.values.count { it.validationOk })
            .put("xray_checked_count", xrayReport.results.size)
            .put("trust", "candidate_selector"))
        performance.put(JSONObject()
            .put("label", "XRAY DIAGNOSTIC — strict=$realValidation — status=$statusMessage — checked=${xrayReport.results.size} — ok=${xrayReport.results.values.count { it.validationOk }} — skipped=${xrayReport.skipped.size}")
            .put("url", "native://xray-diagnostic")
            .put("fetch_ok", true)
            .put("source_score", if (realValidation) 100.0 else 0.0)
            .put("tcp_ok_count", tcpScored.count { it.reachable })
            .put("tcp_candidates", tcpScored.size)
            .put("selected_count", ranked.size)
            .put("xray_ok_count", xrayReport.results.values.count { it.validationOk })
            .put("xray_checked_count", xrayReport.results.size)
            .put("trust", if (realValidation) statusMessage else "tcp_mode"))
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
                .put("deduped", selection.uniqueConfigCount)
                .put("candidate_budget", selection.candidateBudget)
                .put("candidates_selected", selection.selectedCount)
                .put("healthy", tcpScored.count { it.reachable })
                .put("scored", ranked.size)
                .put("sources_checked", parsed.sourcesChecked)
                .put("sources_ok", parsed.sourcesOk)
                .put("real_validation_strict", false)
                .put("real_validation_mode", if (realValidation) "quick_evidence" else "off")
                .put("xray_requested", realValidation)
                .put("xray_budget", selection.xrayBudget)
                .put("xray_status", xrayReport.status)
                .put("xray_status_message", statusMessage)
                .put("xray_checked", xrayReport.results.size)
                .put("xray_ok", xrayReport.results.values.count { it.validationOk })
                .put("xray_skipped", xrayReport.skipped.size))
            .put("configs", configArray)
            .put("items", items)
            .put("failed_sources", failedSources(parsed))
            .put("source_performance", performance)
            .toString()
    }

    private fun validationLabel(item: ScoredConfig, xray: NativeRealValidationResult?, realValidation: Boolean, skipReason: String?): String {
        val tcp = if (item.reachable) {
            "TCP: OK" + (item.latencyMs?.let { " ${it}ms" } ?: "")
        } else {
            "TCP: FAIL"
        }
        val xr = if (!realValidation) {
            "Xray: off"
        } else if (xray == null) {
            "Xray: skipped" + (skipReason?.takeIf { it.isNotBlank() }?.let { " $it" } ?: "")
        } else {
            val status = if (xray.validationOk) "OK" else "FAIL"
            "Xray: $status ${xray.passedProbes}/${xray.totalProbes} conf ${String.format(java.util.Locale.US, "%.2f", xray.confidenceScore)}"
        }
        return "$tcp | $xr"
    }

    private fun runXrayValidation(context: Context, scored: List<ScoredConfig>, budget: Int): XrayReport {
        val binary = File(context.applicationInfo.nativeLibraryDir ?: "", "libxray.so")
        if (!binary.isFile) return XrayReport(emptyMap(), scored.associate { it.config to "xray_binary_missing" }, "missing_binary")
        val workDir = File(context.filesDir, "native-xray-validation")
        if (!workDir.exists()) workDir.mkdirs()
        val validator = NativeXrayValidator()
        val out = linkedMapOf<String, NativeRealValidationResult>()
        val skipped = linkedMapOf<String, String>()
        val candidates = scored.filter { it.reachable }.take(if (budget > 0) budget else 80)
        for (item in candidates) {
            val built = XrayConfigBuilder.build(item.config)
            if (built == null) {
                skipped[item.config] = "xray_config_build_failed"
                continue
            }
            out[item.config] = validator.validate(item.config, binary.absolutePath, built.xrayConfigJson, workDir, built.socksPort)
        }
        for (item in scored.filter { !it.reachable }.take(if (budget > 0) budget else 80)) skipped[item.config] = "tcp_unreachable"
        return XrayReport(out, skipped, "active")
    }

    private fun isXrayBinaryAvailable(context: Context): Boolean = File(context.applicationInfo.nativeLibraryDir ?: "", "libxray.so").isFile
    private fun scoreWithXray(baseScore: Double, xray: NativeRealValidationResult?): Double =
        if (xray?.validationOk == true) maxOf(baseScore, 78.0 + xray.confidenceScore * 22.0).coerceIn(0.0, 100.0) else baseScore
    private fun grade(score: Double): String = when { score >= 90.0 -> "A+"; score >= 80.0 -> "A"; score >= 70.0 -> "B"; score >= 60.0 -> "C"; score >= 45.0 -> "D"; else -> "F" }
    private fun loadSources(context: Context): List<SourceRecord> {
        val registry = BundledSourceRegistry(context)
        val cached = NativeSourceRefreshBridge.cachedRegistryFile(context)
        val sources = if (cached.isFile) registry.loadFromFile(cached) else registry.loadFromAssets("sources.json")
        return sources.sortedWith(
            compareByDescending<SourceRecord> { it.appPriority }
                .thenByDescending { sourceSortScore(it) }
                .thenBy { it.label },
        )
    }
    private fun sourceSortScore(source: SourceRecord): Int {
        var score = 0
        if (source.region.equals("IR", ignoreCase = true)) score += 20
        if (source.mobileProfile.startsWith("iran", ignoreCase = true)) score += 15
        if (source.trust == "medium") score += 10
        if ("mobile-optimized" in source.tags) score += 8
        if ("iran" in source.tags) score += 8
        return score
    }
    private fun failedSources(parsed: NativeFetchParseResult): JSONArray { val out = JSONArray(); for (sourceResult in parsed.sourceResults) if (!sourceResult.ok) out.put(JSONObject().put("url", sourceResult.source.url).put("label", sourceResult.source.label).put("message", sourceResult.fetchResult.error.ifBlank { "no configs extracted" }).put("status_code", sourceResult.fetchResult.statusCode)); return out }
    private data class RankedItem(val base: ScoredConfig, val xray: NativeRealValidationResult?, val finalScore: Double)
    private data class XrayReport(val results: Map<String, NativeRealValidationResult>, val skipped: Map<String, String>, val status: String)
}
