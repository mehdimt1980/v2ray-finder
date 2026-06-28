package org.mehdimt.v2rayfinder.runtime.xray

import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL
import kotlin.math.roundToLong

/** Runs lightweight HTTP probes through the local xray SOCKS proxy. */
class HttpProbeRunner(
    private val connectTimeoutMs: Int = 4_000,
    private val readTimeoutMs: Int = 4_000,
) {
    fun runProbe(endpoint: ProbeEndpoint, socksHost: String, socksPort: Int): ProbeResult {
        val proxy = Proxy(Proxy.Type.SOCKS, InetSocketAddress(socksHost, socksPort))
        val started = System.nanoTime()
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(endpoint.url).openConnection(proxy) as HttpURLConnection).apply {
                requestMethod = "GET"
                instanceFollowRedirects = false
                connectTimeout = connectTimeoutMs
                readTimeout = readTimeoutMs
                setRequestProperty("User-Agent", "v2ray-finder-android-kotlin/phase-5")
            }
            val status = connection.responseCode
            val latency = ((System.nanoTime() - started) / 1_000_000.0).roundToLong()
            ProbeResult(
                name = endpoint.name,
                ok = endpoint.accepts(status),
                statusCode = status,
                latencyMs = latency,
                error = if (endpoint.accepts(status)) "" else "unexpected_status_$status",
            )
        } catch (exc: Exception) {
            ProbeResult(
                name = endpoint.name,
                ok = false,
                error = exc.message ?: exc.javaClass.simpleName,
            )
        } finally {
            connection?.disconnect()
        }
    }

    fun runAll(endpoints: List<ProbeEndpoint>, socksHost: String, socksPort: Int): List<ProbeResult> =
        endpoints.map { runProbe(it, socksHost, socksPort) }
}
