package org.mehdimt.v2rayfinder.runtime.xray

/** One HTTP probe endpoint used through local SOCKS. */
data class ProbeEndpoint(
    val name: String,
    val url: String,
    val expectedStatusMin: Int = 200,
    val expectedStatusMax: Int = 399,
) {
    fun accepts(statusCode: Int): Boolean = statusCode in expectedStatusMin..expectedStatusMax
}

/** Result of one HTTP probe. */
data class ProbeResult(
    val name: String,
    val ok: Boolean,
    val statusCode: Int = 0,
    val latencyMs: Long? = null,
    val error: String = "",
)

/** Native real-validation result for one config. */
data class NativeRealValidationResult(
    val config: String,
    val validationOk: Boolean,
    val confidenceScore: Double,
    val confidenceLevel: String,
    val passedProbes: Int,
    val totalProbes: Int,
    val latencyMs: Long? = null,
    val error: String = "",
    val probeResults: List<ProbeResult> = emptyList(),
)
