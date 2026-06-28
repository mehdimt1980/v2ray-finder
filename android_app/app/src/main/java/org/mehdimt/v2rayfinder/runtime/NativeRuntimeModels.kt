package org.mehdimt.v2rayfinder.runtime

import org.mehdimt.v2rayfinder.registry.SourceRecord

/** Native Kotlin fetch/parse result for one source. */
data class SourceParseResult(
    val source: SourceRecord,
    val fetchResult: FetchResult,
    val rawConfigCount: Int,
    val uniqueConfigCount: Int,
    val configs: List<String>,
) {
    val ok: Boolean
        get() = fetchResult.ok && uniqueConfigCount > 0
}

/** Aggregate result for the Phase 3 native runtime path. */
data class NativeFetchParseResult(
    val sourcesChecked: Int,
    val sourcesOk: Int,
    val rawConfigCount: Int,
    val uniqueConfigCount: Int,
    val configs: List<String>,
    val sourceResults: List<SourceParseResult>,
)
