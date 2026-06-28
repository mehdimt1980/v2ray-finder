package org.mehdimt.v2rayfinder.runtime

import android.util.Base64
import org.json.JSONObject
import java.net.URI

/**
 * Extracts host and port from supported config URI formats.
 *
 * Phase 4 focuses on endpoint reachability. Unsupported or ambiguous configs are
 * skipped instead of causing the scan to fail.
 */
object EndpointParser {
    fun parse(config: String): Endpoint? {
        val protocol = ProtocolDetector.detect(config)
        return when (protocol) {
            "vless", "trojan" -> parseStandardUri(config, protocol)
            "vmess" -> parseVmess(config)
            "ss" -> parseShadowsocks(config)
            else -> null
        }?.takeIf { it.isUsable }
    }

    private fun parseStandardUri(config: String, protocol: String): Endpoint? = try {
        val uri = URI(config.trim())
        val host = uri.host ?: return null
        val port = uri.port
        Endpoint(host = host, port = port, protocol = protocol)
    } catch (_: Exception) {
        null
    }

    private fun parseVmess(config: String): Endpoint? = try {
        val payload = config.substringAfter("vmess://", "").trim()
        if (payload.isBlank()) return null
        val json = String(Base64.decode(padBase64(payload), Base64.DEFAULT), Charsets.UTF_8)
        val obj = JSONObject(json)
        val host = obj.optString("add", "").trim()
        val port = obj.optString("port", "").trim().toIntOrNull() ?: obj.optInt("port", -1)
        Endpoint(host = host, port = port, protocol = "vmess")
    } catch (_: Exception) {
        null
    }

    private fun parseShadowsocks(config: String): Endpoint? = try {
        val raw = config.substringAfter("ss://", "")
            .substringBefore('#')
            .substringBefore('?')
            .trim()
        if (raw.isBlank()) return null

        val hostPort = if (raw.contains('@')) {
            raw.substringAfterLast('@')
        } else {
            val decoded = tryDecodeBase64(raw) ?: raw
            decoded.substringAfterLast('@')
        }

        parseHostPort(hostPort, "ss")
    } catch (_: Exception) {
        null
    }

    private fun parseHostPort(value: String, protocol: String): Endpoint? {
        val clean = value.trim()
        if (clean.isBlank()) return null

        if (clean.startsWith("[")) {
            val end = clean.indexOf(']')
            if (end <= 0) return null
            val host = clean.substring(1, end)
            val port = clean.substring(end + 1).removePrefix(":").toIntOrNull() ?: return null
            return Endpoint(host = host, port = port, protocol = protocol)
        }

        val host = clean.substringBeforeLast(':', "")
        val port = clean.substringAfterLast(':', "").toIntOrNull() ?: return null
        return Endpoint(host = host, port = port, protocol = protocol)
    }

    private fun tryDecodeBase64(value: String): String? = try {
        String(Base64.decode(padBase64(value), Base64.DEFAULT), Charsets.UTF_8)
    } catch (_: Exception) {
        null
    }

    private fun padBase64(value: String): String {
        val compact = value.trim().replace('-', '+').replace('_', '/')
        val padding = (4 - compact.length % 4) % 4
        return compact + "=".repeat(padding)
    }
}
