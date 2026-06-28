package org.mehdimt.v2rayfinder.runtime

import kotlin.math.max

/**
 * Native Phase 4 scoring for TCP-checked configs.
 *
 * This is intentionally simple and deterministic. Real validation weighting will
 * be added later in Phase 5 after xray orchestration is native.
 */
object NativeScoringEngine {
    fun score(results: List<TcpHealthResult>): List<ScoredConfig> =
        results.map { scoreOne(it) }
            .sortedWith(compareByDescending<ScoredConfig> { it.score }.thenBy { it.latencyMs ?: Long.MAX_VALUE })

    fun scoreOne(result: TcpHealthResult): ScoredConfig {
        val protocol = result.endpoint?.protocol ?: ProtocolDetector.detect(result.config)
        val protocolScore = protocolBaseScore(protocol)
        val reachabilityScore = if (result.reachable) 45.0 else 0.0
        val latencyScore = latencyScore(result.latencyMs)
        val total = (protocolScore + reachabilityScore + latencyScore).coerceIn(0.0, 100.0)

        return ScoredConfig(
            config = result.config,
            protocol = protocol,
            reachable = result.reachable,
            latencyMs = result.latencyMs,
            score = total,
            grade = grade(total),
        )
    }

    private fun protocolBaseScore(protocol: String): Double = when (protocol.lowercase()) {
        "vless" -> 24.0
        "trojan" -> 22.0
        "vmess" -> 20.0
        "ss" -> 18.0
        "ssr" -> 14.0
        else -> 8.0
    }

    private fun latencyScore(latencyMs: Long?): Double {
        if (latencyMs == null) return 0.0
        if (latencyMs <= 0) return 20.0
        val penalty = latencyMs / 50.0
        return max(0.0, 30.0 - penalty)
    }

    private fun grade(score: Double): String = when {
        score >= 90.0 -> "A+"
        score >= 80.0 -> "A"
        score >= 70.0 -> "B"
        score >= 60.0 -> "C"
        score >= 45.0 -> "D"
        else -> "F"
    }
}
