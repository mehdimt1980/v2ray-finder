package org.mehdimt.v2rayfinder.runtime

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import org.mehdimt.v2rayfinder.registry.BundledSourceRegistry
import org.mehdimt.v2rayfinder.registry.NativeSourceRefreshBridge
import org.mehdimt.v2rayfinder.registry.SourceRecord

object NativeScanBridge {
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
        val configArray = JSONArray()
        val items = JSONArray()
        for (config in configs) configArray.put(config)
        for (item in scored) {
            val source = sourceByConfig[item.config]
            val sourceUrl = source?.url ?: ""
            val sourceLabel = source?.label ?: ""
            items.put(JSONObject()
                .put("config", item.config)
                .put("protocol", item.protocol)
                .put("grade", item.grade)
                .put("total", item.score)
                .put("latency_ms", item.latencyMs ?: JSONObject.NULL)
                .put("source", sourceUrl)
                .put("source_label", sourceLabel)
                .put("xray_checked", false)
                .put("xray_note", if (realValidation) "xray native validation is not active in this build yet" else ""))
        }
        val performance = JSONArray()
        for (sourceResult in parsed.sourceResults) {
            performance.put(JSONObject()
                .put("label", sourceResult.source.label)
                .put("url", sourceResult.source.url)
                .put("fetch_ok", sourceResult.fetchResult.ok)
                .put("source_score", if (sourceResult.ok) 50.0 else 0.0)
                .put("tcp_ok_count", checks.count { sourceByConfig[it.config]?.url == sourceResult.source.url && it.reachable })
                .put("tcp_candidates", sourceResult.uniqueConfigCount)
                .put("xray_ok_count", 0)
                .put("xray_checked_count", 0)
                .put("trust", sourceResult.source.trust))
        }
        return JSONObject()
            .put("stats", JSONObject()
                .put("fetched", parsed.rawConfigCount)
                .put("deduped", configs.size)
                .put("healthy", scored.count { it.reachable })
                .put("scored", scored.size))
            .put("configs", configArray)
            .put("items", items)
            .put("failed_sources", failedSources(parsed))
            .put("source_performance", performance)
            .toString()
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
