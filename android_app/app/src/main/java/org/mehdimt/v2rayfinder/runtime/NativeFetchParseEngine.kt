package org.mehdimt.v2rayfinder.runtime

import org.mehdimt.v2rayfinder.registry.SourceRecord

/**
 * Phase 3 native runtime engine: fetch sources, extract configs and deduplicate.
 *
 * This is intentionally not connected to MainActivity yet. Later phases will add
 * health checks, scoring and an explicit UI/runtime switch after this compiles.
 */
class NativeFetchParseEngine(
    private val fetcher: SourceFetcher = SourceFetcher(),
) {
    fun run(sources: List<SourceRecord>, limit: Int = DEFAULT_LIMIT): NativeFetchParseResult {
        val boundedSources = if (limit > 0) sources.take(limit) else sources
        val sourceResults = mutableListOf<SourceParseResult>()
        val allConfigs = mutableListOf<String>()
        var rawConfigCount = 0

        for (source in boundedSources) {
            val fetched = fetcher.fetch(source.url)
            val extracted = if (fetched.ok) ConfigExtractor.extract(fetched.body) else emptyList()
            rawConfigCount += extracted.size
            allConfigs += extracted
            sourceResults += SourceParseResult(
                source = source,
                fetchResult = fetched,
                rawConfigCount = extracted.size,
                uniqueConfigCount = extracted.size,
                configs = extracted,
            )
        }

        val unique = ConfigDeduplicator.deduplicate(allConfigs)
        return NativeFetchParseResult(
            sourcesChecked = boundedSources.size,
            sourcesOk = sourceResults.count { it.ok },
            rawConfigCount = rawConfigCount,
            uniqueConfigCount = unique.size,
            configs = unique,
            sourceResults = sourceResults,
        )
    }

    companion object {
        const val DEFAULT_LIMIT: Int = 50
    }
}
