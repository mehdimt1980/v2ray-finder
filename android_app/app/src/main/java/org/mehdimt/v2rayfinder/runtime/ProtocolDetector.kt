package org.mehdimt.v2rayfinder.runtime

/** Lightweight protocol detection for extracted proxy config URIs. */
object ProtocolDetector {
    fun detect(config: String): String {
        val value = config.trim().lowercase()
        return when {
            value.startsWith("vmess://") -> "vmess"
            value.startsWith("vless://") -> "vless"
            value.startsWith("trojan://") -> "trojan"
            value.startsWith("ss://") -> "ss"
            value.startsWith("ssr://") -> "ssr"
            else -> "unknown"
        }
    }

    fun isSupported(config: String): Boolean = detect(config) != "unknown"
}
