package org.mehdimt.v2rayfinder.runtime

/** Result of fetching one source URL in the native Kotlin runtime path. */
data class FetchResult(
    val url: String,
    val ok: Boolean,
    val statusCode: Int = 0,
    val body: String = "",
    val error: String = "",
)
