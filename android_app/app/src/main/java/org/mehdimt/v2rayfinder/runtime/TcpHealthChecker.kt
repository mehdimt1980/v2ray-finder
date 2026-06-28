package org.mehdimt.v2rayfinder.runtime

import java.net.InetSocketAddress
import java.net.Socket
import kotlin.math.roundToLong

/** Native TCP reachability checker for Phase 4. */
class TcpHealthChecker(
    private val timeoutMs: Int = DEFAULT_TIMEOUT_MS,
) {
    fun check(config: String): TcpHealthResult {
        val endpoint = EndpointParser.parse(config)
            ?: return TcpHealthResult(config = config, endpoint = null, reachable = false, error = "endpoint_parse_failed")

        val started = System.nanoTime()
        return try {
            Socket().use { socket ->
                socket.connect(InetSocketAddress(endpoint.host, endpoint.port), timeoutMs)
            }
            val latency = ((System.nanoTime() - started) / 1_000_000.0).roundToLong()
            TcpHealthResult(config = config, endpoint = endpoint, reachable = true, latencyMs = latency)
        } catch (exc: Exception) {
            TcpHealthResult(
                config = config,
                endpoint = endpoint,
                reachable = false,
                error = exc.message ?: exc.javaClass.simpleName,
            )
        }
    }

    fun checkAll(configs: List<String>, limit: Int = DEFAULT_LIMIT): List<TcpHealthResult> {
        val bounded = if (limit > 0) configs.take(limit) else configs
        return bounded.map { check(it) }
    }

    companion object {
        const val DEFAULT_TIMEOUT_MS: Int = 4_000
        const val DEFAULT_LIMIT: Int = 200
    }
}
