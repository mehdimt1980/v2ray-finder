package org.mehdimt.v2rayfinder.runtime

import android.util.Base64

/**
 * Extracts proxy config URIs from raw subscriptions, base64 subscriptions and
 * simple Clash/YAML-like text.
 */
object ConfigExtractor {
    private val configRegex = Regex(
        pattern = "(?i)(vmess|vless|trojan|ssr|ss)://[^\\s\\\"'<>]+",
        options = setOf(RegexOption.IGNORE_CASE),
    )

    fun extract(text: String): List<String> {
        if (text.isBlank()) return emptyList()

        val candidates = mutableListOf<String>()
        candidates += extractDirect(text)

        val decoded = decodeBase64Subscription(text)
        if (!decoded.isNullOrBlank() && decoded != text) {
            candidates += extractDirect(decoded)
        }

        return ConfigDeduplicator.deduplicate(candidates)
    }

    private fun extractDirect(text: String): List<String> =
        configRegex.findAll(text)
            .map { it.value.trim().trimEnd(',', ';') }
            .filter { ProtocolDetector.isSupported(it) }
            .toList()

    private fun decodeBase64Subscription(text: String): String? {
        val compact = text
            .lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .joinToString(separator = "")
            .trim()

        if (compact.length < MIN_BASE64_LENGTH) return null
        if (!compact.matches(BASE64_LIKE)) return null

        val padded = compact.padEnd(compact.length + ((4 - compact.length % 4) % 4), '=')
        return try {
            val bytes = Base64.decode(padded, Base64.DEFAULT)
            String(bytes, Charsets.UTF_8).takeIf { decoded -> decoded.contains("://") }
        } catch (_: Exception) {
            null
        }
    }

    private const val MIN_BASE64_LENGTH: Int = 32
    private val BASE64_LIKE = Regex("^[A-Za-z0-9+/=_-]+$")
}
