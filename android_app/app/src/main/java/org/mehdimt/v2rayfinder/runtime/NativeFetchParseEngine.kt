package org.mehdimt.v2rayfinder.runtime

import org.mehdimt.v2rayfinder.registry.SourceRecord

/** Native runtime engine: fetch sources, extract configs, early-sample and deduplicate. */
class NativeFetchParseEngine(
    private val fetcher: SourceFetcher = SourceFetcher(),
) {
    fun run(
        sources: List<SourceRecord>,
        limit: Int = DEFAULT_LIMIT,
        perSourceLimit: Int = DEFAULT_PER_SOURCE_LIMIT,
    ): NativeFetchParseResult {
        val boundedSources = if (limit > 0) sources.take(limit) else sources
        val sourceResults = mutableListOf<SourceParseResult>()
        val sampledConfigs = mutableListOf<String>()
        var rawConfigCount = 0

        for (source in boundedSources) {
            val fetched = fetcher.fetch(source.url)
            val extracted = if (fetched.ok) ConfigExtractor.extract(fetched.body) else emptyList()
            rawConfigCount += extracted.size
            val unique = ConfigDeduplicator.deduplicate(extracted)
            val sampled = sampleWithinSource(unique, perSourceLimit)
            sampledConfigs += sampled
            sourceResults += SourceParseResult(
                source = source,
                fetchResult = fetched,
                rawConfigCount = extracted.size,
                uniqueConfigCount = unique.size,
                configs = sampled,
            )
        }

        val uniqueSampled = ConfigDeduplicator.deduplicate(sampledConfigs)
        return NativeFetchParseResult(
            sourcesChecked = boundedSources.size,
            sourcesOk = sourceResults.count { it.ok },
            rawConfigCount = rawConfigCount,
            uniqueConfigCount = uniqueSampled.size,
            configs = uniqueSampled,
            sourceResults = sourceResults,
        )
    }

    private fun sampleWithinSource(configs: List<String>, limit: Int): List<String> {
        if (limit <= 0 || configs.size <= limit) return configs
        val head = (limit * 0.20).toInt().coerceAtLeast(8)
        val tail = (limit * 0.20).toInt().coerceAtLeast(8)
        val top = (limit * 0.45).toInt().coerceAtLeast(16)
        val out = linkedSetOf<String>()
        out += configs.take(head)
        out += configs.takeLast(tail)
        out += configs.sortedByDescending { CandidateSelector.cheapScore(it) }.take(top)
        var index = 0
        while (out.size < limit && index < configs.size) {
            out += configs[index]
            index += 3
        }
        return out.take(limit)
    }

    companion object {
        const val DEFAULT_LIMIT: Int = 50
        const val DEFAULT_PER_SOURCE_LIMIT: Int = 90
    }
}
