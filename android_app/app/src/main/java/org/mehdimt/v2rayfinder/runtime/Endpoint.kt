package org.mehdimt.v2rayfinder.runtime

/** Network endpoint extracted from a proxy config for TCP reachability checks. */
data class Endpoint(
    val host: String,
    val port: Int,
    val protocol: String,
) {
    val isUsable: Boolean
        get() = host.isNotBlank() && port in 1..65535
}
