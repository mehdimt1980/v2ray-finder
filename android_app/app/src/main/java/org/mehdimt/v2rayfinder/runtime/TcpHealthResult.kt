package org.mehdimt.v2rayfinder.runtime

/** Result of one TCP reachability attempt. */
data class TcpHealthResult(
    val config: String,
    val endpoint: Endpoint?,
    val reachable: Boolean,
    val latencyMs: Long? = null,
    val error: String = "",
)
