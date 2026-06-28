package org.mehdimt.v2rayfinder.runtime

import org.mehdimt.v2rayfinder.registry.SourceRecord
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Native runtime engine: fetch sources concurrently, extract configs, early-sample and deduplicate. */
class NativeFetchParseEngine(
    private val fetcher: SourceFetcher = SourceFetcher(),
    private val concurrency: Int = DEFAULT_CONCURRENCY,
) {
    fun run(
        sources: List<SourceRecord>,
        limit: Int = DEFAULT_LIMIT,
        perSourceLimit: Int = DEFAULT_PER_SOURCE_LIMIT,
    ): NativeFetchParseResult {
        val boundedSources = if (limit > 0) sources.take(limit) else sources
        if (boundedSources.isEmpty()) {
            return NativeFetchParseResult(0, 0, 0, 0, emptyList(), emptyList())
        }

        val poolSize = concurrency.coerceIn(1, 12).coerceAtMost(boundedSources.size)
        val executor = Executors.newFixedThreadPool(poolSize)
        val sourceResults = try {
            val tasks = boundedSources.map { source ->
                Callable { fetchParseOne(source, perSourceLimit) }
            }
            executor.invokeAll(tasks, globalTimeoutMs(boundedSources.size, poolSize), TimeUnit.MILLISECONDS)
                .mapIndexed { index, future ->
                    try {
                        if (future.isCancelled) failedResult(boundedSources[index], "source_fetch_cancelled") else future.get()
                    } catch (exc: Exception) {
                        failedResult(boundedSources[index], exc.message ?: exc.javaClass.simpleName)
                    }
                }
        } finally {
            executor.shutdownNow()
        }

        val sampledConfigs = sourceResults.flatMap { it.configs }
        val uniqueSampled = ConfigDeduplicator.deduplicate(sampledConfigs)
        return NativeFetchParseResult(
            sourcesChecked = boundedSources.size,
            sourcesOk = sourceResults.count { it.ok },
            rawConfigCount = sourceResults.sumOf { it.rawConfigCount },
            uniqueConfigCount = uniqueSampled.size,
            configs = uniqueSampled,
            sourceResults = sourceResults,
        )
    }

    private fun fetchParseOne(source: SourceRecord, perSourceLimit: Int): SourceParseResult {
        val fetched = fetcher.fetch(source.url)
        val extracted = if (fetched.ok) ConfigExtractor.extract(fetched.body) else emptyList()
        val unique = ConfigDeduplicator.deduplicate(extracted)
        val sampled = sampleWithinSource(unique, perSourceLimit)
        return SourceParseResult(
            source = source,
            fetchResult = fetched,
            rawConfigCount = extracted.size,
            uniqueConfigCount = unique.size,
            configs = sampled,
        )
    }

    private fun failedResult(source: SourceRecord, error: String): SourceParseResult {
        return SourceParseResult(
            source = source,
            fetchResult = FetchResult(url = source.url, ok = false, error = error),
            rawConfigCount = 0,
            uniqueConfigCount = 0,
            configs = emptyList(),
        )
    }

    private fun globalTimeoutMs(count: Int, poolSize: Int): Long {
        val waves = ((count + poolSize - 1) / poolSize).coerceAtLeast(1)
        return (waves * SourceFetcher.DEFAULT_TIMEOUT_MS + 2_000L).coerceAtMost(18_000L)
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
        const val DEFAULT_CONCURRENCY: Int = 8
    }
}
