package org.mehdimt.v2rayfinder.runtime

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import org.mehdimt.v2rayfinder.registry.BundledSourceRegistry

object NativeScanBridge {
    @JvmStatic
    fun scan(context: Context, limit: Int, timeoutSeconds: Double, health: Boolean, token: String): String {
        val maxConfigs = if (limit > 0) limit else 200
        val timeoutMs = (timeoutSeconds.coerceAtLeast(1.0) * 1000.0).toInt()
        val sources = BundledSourceRegistry(context).loadFromAssets("sources.json")
        val parsed = NativeFetchParseEngine(SourceFetcher(timeoutMs, timeoutMs)).run(sources, 50)
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
            items.put(JSONObject()
                .put("config", item.config)
                .put("protocol", item.protocol)
                .put("grade", item.grade)
                .put("total", item.score)
                .put("latency_ms", item.latencyMs ?: JSONObject.NULL)
                .put("source", "native-kotlin"))
        }
        return JSONObject()
            .put("stats", JSONObject()
                .put("fetched", parsed.rawConfigCount)
                .put("deduped", configs.size)
                .put("healthy", scored.count { it.reachable })
                .put("scored", scored.size))
            .put("configs", configArray)
            .put("items", items)
            .put("failed_sources", JSONArray())
            .put("source_performance", JSONArray())
            .toString()
    }
}
