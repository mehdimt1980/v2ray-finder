package org.mehdimt.v2rayfinder.runtime

import org.mehdimt.v2rayfinder.registry.SourceRecord
import java.net.URI
import java.security.MessageDigest
import java.time.LocalDate
import java.util.Random
import kotlin.math.max

object CandidateSelector {
    const val DEFAULT_XRAY_BUDGET: Int = 10

    fun select(
        parsed: NativeFetchParseResult,
        userLimit: Int,
        realValidation: Boolean,
    ): CandidateSelection {
        val desired = if (userLimit > 0) userLimit else 200
        val candidateBudget = fastCandidateBudget(desired, realValidation)
        val xrayBudget = if (realValidation) DEFAULT_XRAY_BUDGET.coerceAtMost(candidateBudget) else 0
        val attribution = buildAttribution(parsed)
        val perSource = parsed.sourceResults
            .filter { it.configs.isNotEmpty() }
            .map { sourceResult ->
                val unique = ConfigDeduplicator.deduplicate(sourceResult.configs)
                SourceBucket(
                    source = sourceResult.source,
                    configs = diversifyWithinSource(unique, sourceResult.source.url, desired),
                )
            }
            .filter { it.configs.isNotEmpty() }

        val selected = mutableListOf<String>()
        val seen = linkedSetOf<String>()
        var cursor = 0
        while (selected.size < candidateBudget && perSource.any { cursor < it.configs.size }) {
            for (bucket in perSource) {
                if (cursor >= bucket.configs.size) continue
                val config = bucket.configs[cursor]
                if (seen.add(config)) selected += config
                if (selected.size >= candidateBudget) break
            }
            cursor++
        }

        if (selected.size < candidateBudget) {
            val fallback = parsed.configs.sortedByDescending { cheapScore(it) }
            for (config in fallback) {
                if (seen.add(config)) selected += config
                if (selected.size >= candidateBudget) break
            }
        }

        return CandidateSelection(
            configs = selected,
            attribution = attribution,
            rawConfigCount = parsed.rawConfigCount,
            uniqueConfigCount = parsed.uniqueConfigCount,
            candidateBudget = candidateBudget,
            xrayBudget = xrayBudget,
            selectedCount = selected.size,
        )
    }

    private fun fastCandidateBudget(desired: Int, realValidation: Boolean): Int {
        val multiplier = if (realValidation) 1 else 2
        val floor = if (realValidation) 80 else 160
        val ceiling = if (realValidation) 160 else 260
        return max(floor, desired * multiplier).coerceAtMost(ceiling)
    }

    fun cheapScore(config: String): Int {
        val lower = config.lowercase()
        var score = 0
        when (ProtocolDetector.detect(config)) {
            "vless" -> score += 28
            "trojan" -> score += 24
            "vmess" -> score += 18
            "ss" -> score += 12
            else -> score -= 30
        }
        if ("security=reality" in lower) score += 34
        if ("security=tls" in lower || "tls" in lower) score += 20
        if ("type=ws" in lower || "net=ws" in lower || "websocket" in lower) score += 12
        if ("type=grpc" in lower || "net=grpc" in lower) score += 12
        if ("httpupgrade" in lower) score += 8
        if ("sni=" in lower || "servername=" in lower) score += 8
        if ("host=" in lower) score += 6
        if ("path=" in lower || "serviceName=" in config) score += 6
        if (":443" in lower) score += 10
        if (":8443" in lower || ":2053" in lower || ":2087" in lower || ":2096" in lower) score += 6
        if (lower.length < 24) score -= 50
        if (lower.contains("localhost") || lower.contains("127.0.0.1")) score -= 100
        if (extractHost(config).isBlank()) score -= 25
        return score
    }

    private fun diversifyWithinSource(configs: List<String>, sourceUrl: String, desired: Int): List<String> {
        if (configs.size <= 3) return configs
        val headCount = max(8, desired / 20).coerceAtMost(configs.size)
        val tailCount = max(8, desired / 20).coerceAtMost(configs.size)
        val topScoreCount = max(24, desired / 4).coerceAtMost(configs.size)
        val randomCount = max(24, desired / 2).coerceAtMost(configs.size)
        val out = linkedSetOf<String>()
        out += configs.take(headCount)
        out += configs.takeLast(tailCount)
        out += configs.sortedByDescending { cheapScore(it) }.take(topScoreCount)
        out += deterministicSample(configs, sourceUrl, randomCount)
        return out.sortedByDescending { cheapScore(it) }
    }

    private fun deterministicSample(configs: List<String>, sourceUrl: String, count: Int): List<String> {
        if (configs.size <= count) return configs
        val seed = stableSeed(LocalDate.now().toString() + sourceUrl)
        val copy = configs.toMutableList()
        val random = Random(seed)
        for (i in copy.indices.reversed()) {
            val j = random.nextInt(i + 1)
            val tmp = copy[i]
            copy[i] = copy[j]
            copy[j] = tmp
        }
        return copy.take(count)
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

    private fun extractHost(config: String): String {
        return try {
            when (ProtocolDetector.detect(config)) {
                "vmess" -> "vmess-host-unknown"
                "ss" -> config.substringAfter('@', "").substringBeforeLast(':', "")
                else -> URI(config).host ?: ""
            }
        } catch (_: Exception) {
            ""
        }
    }

    private fun stableSeed(value: String): Long {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        var out = 0L
        for (i in 0 until 8) out = (out shl 8) or (digest[i].toLong() and 0xff)
        return out
    }

    private data class SourceBucket(val source: SourceRecord, val configs: List<String>)
}

data class CandidateSelection(
    val configs: List<String>,
    val attribution: Map<String, List<SourceRecord>>,
    val rawConfigCount: Int,
    val uniqueConfigCount: Int,
    val candidateBudget: Int,
    val xrayBudget: Int,
    val selectedCount: Int,
)
