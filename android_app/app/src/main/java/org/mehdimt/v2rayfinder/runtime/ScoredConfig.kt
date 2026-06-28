package org.mehdimt.v2rayfinder.runtime

/** Phase 4 native score result for one config. */
data class ScoredConfig(
    val config: String,
    val protocol: String,
    val reachable: Boolean,
    val latencyMs: Long? = null,
    val score: Double,
    val grade: String,
)
