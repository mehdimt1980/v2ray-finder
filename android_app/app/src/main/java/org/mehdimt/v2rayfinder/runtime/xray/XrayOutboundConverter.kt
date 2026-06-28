package org.mehdimt.v2rayfinder.runtime.xray

import android.net.Uri
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import org.mehdimt.v2rayfinder.runtime.ProtocolDetector

/** Converts common proxy URI formats into xray outbound JSON. */
object XrayOutboundConverter {
    fun convert(config: String): XrayOutboundConversion? {
        return when (ProtocolDetector.detect(config)) {
            "vless" -> convertVless(config)
            "trojan" -> convertTrojan(config)
            "vmess" -> convertVmess(config)
            "ss" -> convertShadowsocks(config)
            else -> null
        }
    }

    private fun convertVless(config: String): XrayOutboundConversion? = try {
        val uri = Uri.parse(config)
        val uuid = uri.userInfo?.takeIf { it.isNotBlank() } ?: return null
        val host = uri.host ?: return null
        val port = uri.port.takeIf { it in 1..65535 } ?: return null
        val security = uri.getQueryParameter("security") ?: "none"
        val network = uri.getQueryParameter("type") ?: "tcp"
        val flow = uri.getQueryParameter("flow") ?: ""
        val sni = uri.getQueryParameter("sni") ?: uri.getQueryParameter("serverName") ?: host
        val fp = uri.getQueryParameter("fp") ?: "chrome"
        val pbk = uri.getQueryParameter("pbk") ?: ""
        val sid = uri.getQueryParameter("sid") ?: ""
        val path = uri.getQueryParameter("path") ?: uri.getQueryParameter("serviceName") ?: ""
        val hostHeader = uri.getQueryParameter("host") ?: uri.getQueryParameter("authority") ?: ""
        val user = JSONObject().put("id", uuid).put("encryption", "none")
        if (flow.isNotBlank()) user.put("flow", flow)
        val outbound = baseOutbound("vless")
            .put("settings", JSONObject().put("vnext", JSONArray().put(JSONObject().put("address", host).put("port", port).put("users", JSONArray().put(user)))))
            .put("streamSettings", streamSettings(security, network, sni, fp, pbk, sid, path, hostHeader))
        XrayOutboundConversion("vless", outbound)
    } catch (_: Exception) { null }

    private fun convertTrojan(config: String): XrayOutboundConversion? = try {
        val uri = Uri.parse(config)
        val password = uri.userInfo?.takeIf { it.isNotBlank() } ?: return null
        val host = uri.host ?: return null
        val port = uri.port.takeIf { it in 1..65535 } ?: return null
        val security = uri.getQueryParameter("security") ?: "tls"
        val network = uri.getQueryParameter("type") ?: "tcp"
        val sni = uri.getQueryParameter("sni") ?: uri.getQueryParameter("serverName") ?: host
        val fp = uri.getQueryParameter("fp") ?: "chrome"
        val path = uri.getQueryParameter("path") ?: uri.getQueryParameter("serviceName") ?: ""
        val hostHeader = uri.getQueryParameter("host") ?: uri.getQueryParameter("authority") ?: ""
        val outbound = baseOutbound("trojan")
            .put("settings", JSONObject().put("servers", JSONArray().put(JSONObject().put("address", host).put("port", port).put("password", password))))
            .put("streamSettings", streamSettings(security, network, sni, fp, "", "", path, hostHeader))
        XrayOutboundConversion("trojan", outbound)
    } catch (_: Exception) { null }

    private fun convertVmess(config: String): XrayOutboundConversion? = try {
        val payload = config.substringAfter("vmess://", "").trim()
        if (payload.isBlank()) return null
        val src = JSONObject(String(Base64.decode(padBase64(payload), Base64.DEFAULT), Charsets.UTF_8))
        val host = src.optString("add", "").trim().ifBlank { return null }
        val port = src.optString("port", "").trim().toIntOrNull() ?: src.optInt("port", -1)
        if (port !in 1..65535) return null
        val uuid = src.optString("id", "").trim().ifBlank { return null }
        val user = JSONObject().put("id", uuid).put("alterId", src.optString("aid", "0").trim().toIntOrNull() ?: src.optInt("aid", 0)).put("security", src.optString("scy", "auto").ifBlank { "auto" })
        val outbound = baseOutbound("vmess")
            .put("settings", JSONObject().put("vnext", JSONArray().put(JSONObject().put("address", host).put("port", port).put("users", JSONArray().put(user)))))
            .put("streamSettings", streamSettings(src.optString("tls", "").ifBlank { "none" }, src.optString("net", "tcp").ifBlank { "tcp" }, src.optString("sni", "").ifBlank { src.optString("host", host).ifBlank { host } }, src.optString("fp", "chrome").ifBlank { "chrome" }, "", "", src.optString("path", ""), src.optString("host", "")))
        XrayOutboundConversion("vmess", outbound)
    } catch (_: Exception) { null }

    private fun convertShadowsocks(config: String): XrayOutboundConversion? = try {
        val raw = config.substringAfter("ss://", "").substringBefore('#').substringBefore('?').trim()
        if (raw.isBlank()) return null
        val decoded = if (raw.contains('@')) raw else tryDecodeBase64(raw) ?: raw
        val methodPassword = decoded.substringBeforeLast('@', "")
        val hostPort = decoded.substringAfterLast('@', "")
        if (methodPassword.isBlank() || hostPort.isBlank()) return null
        val method = methodPassword.substringBefore(':', "")
        val password = methodPassword.substringAfter(':', "")
        val host = hostPort.substringBeforeLast(':', "")
        val port = hostPort.substringAfterLast(':', "").toIntOrNull() ?: return null
        if (method.isBlank() || password.isBlank() || host.isBlank() || port !in 1..65535) return null
        XrayOutboundConversion("ss", baseOutbound("shadowsocks").put("settings", JSONObject().put("servers", JSONArray().put(JSONObject().put("address", host).put("port", port).put("method", method).put("password", password)))))
    } catch (_: Exception) { null }

    private fun baseOutbound(protocol: String): JSONObject = JSONObject().put("tag", "proxy").put("protocol", protocol)

    private fun streamSettings(security: String, network: String, sni: String, fingerprint: String, publicKey: String, shortId: String, path: String, hostHeader: String): JSONObject {
        val normalizedSecurity = if (security.isBlank()) "none" else security
        val networkRaw = if (network.isBlank()) "tcp" else network.lowercase()
        val normalizedNetwork = if (networkRaw == "websocket") "ws" else networkRaw
        val out = JSONObject().put("network", normalizedNetwork).put("security", normalizedSecurity)
        if (normalizedSecurity == "tls") out.put("tlsSettings", JSONObject().put("serverName", sni))
        if (normalizedSecurity == "reality") {
            val reality = JSONObject().put("serverName", sni).put("fingerprint", fingerprint)
            if (publicKey.isNotBlank()) reality.put("publicKey", publicKey)
            if (shortId.isNotBlank()) reality.put("shortId", shortId)
            out.put("realitySettings", reality)
        }
        if (normalizedNetwork == "ws") {
            val ws = JSONObject()
            if (path.isNotBlank()) ws.put("path", path)
            if (hostHeader.isNotBlank()) ws.put("headers", JSONObject().put("Host", hostHeader))
            out.put("wsSettings", ws)
        }
        if (normalizedNetwork == "grpc") {
            val grpc = JSONObject()
            if (path.isNotBlank()) grpc.put("serviceName", path)
            out.put("grpcSettings", grpc)
        }
        if (normalizedNetwork == "httpupgrade") {
            val http = JSONObject()
            if (path.isNotBlank()) http.put("path", path)
            if (hostHeader.isNotBlank()) http.put("host", hostHeader)
            out.put("httpupgradeSettings", http)
        }
        return out
    }

    private fun tryDecodeBase64(value: String): String? = try { String(Base64.decode(padBase64(value), Base64.DEFAULT), Charsets.UTF_8) } catch (_: Exception) { null }
    private fun padBase64(value: String): String { val compact = value.trim().replace('-', '+').replace('_', '/'); return compact + "=".repeat((4 - compact.length % 4) % 4) }
}
