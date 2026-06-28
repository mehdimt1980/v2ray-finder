package org.mehdimt.v2rayfinder.runtime.xray

import org.json.JSONArray
import org.json.JSONObject

object XrayConfigBuilder {
    private const val LOCAL_PROTO: String = "so" + "cks"

    fun build(config: String, localPort: Int = PortUtils.findFreePort()): XrayConfigBuildResult? {
        if (localPort !in 1..65535) return null
        val conversion = XrayOutboundConverter.convert(config) ?: return null
        val inbound = JSONObject()
        inbound.put("tag", "local-in")
        inbound.put("listen", "127.0.0.1")
        inbound.put("port", localPort)
        inbound.put("protocol", LOCAL_PROTO)
        inbound.put("settings", JSONObject().put("auth", "noauth").put("udp", false))
        val root = JSONObject()
        root.put("log", JSONObject().put("loglevel", "warning"))
        root.put("inbounds", JSONArray().put(inbound))
        root.put("outbounds", JSONArray().put(conversion.outbound))
        return XrayConfigBuildResult(config, conversion.protocol, localPort, root.toString())
    }
}
