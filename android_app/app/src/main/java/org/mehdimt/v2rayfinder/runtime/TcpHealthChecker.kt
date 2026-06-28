package org.mehdimt.v2rayfinder.runtime

import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.roundToLong

/** Native TCP reachability checker. */
class TcpHealthChecker(
    private val timeoutMs: Int = DEFAULT_TIMEOUT_MS,
    private val concurrency: Int = DEFAULT_CONCURRENCY,
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
        if (bounded.isEmpty()) return emptyList()
        val poolSize = concurrency.coerceIn(1, 64).coerceAtMost(bounded.size)
        val executor = Executors.newFixedThreadPool(poolSize)
        return try {
            val tasks = bounded.map { config -> Callable { check(config) } }
            executor.invokeAll(tasks, globalTimeoutMs(bounded.size, poolSize), TimeUnit.MILLISECONDS)
                .mapIndexed { index, future ->
                    try {
                        if (future.isCancelled) timeoutResult(bounded[index]) else future.get()
                    } catch (exc: Exception) {
                        timeoutResult(bounded[index], exc.message ?: exc.javaClass.simpleName)
                    }
                }
        } finally {
            executor.shutdownNow()
        }
    }

    private fun globalTimeoutMs(count: Int, poolSize: Int): Long {
        val waves = ((count + poolSize - 1) / poolSize).coerceAtLeast(1)
        return (waves * timeoutMs + 1_500L).coerceAtMost(25_000L)
    }

    private fun timeoutResult(config: String, error: String = "tcp_timeout_cancelled"): TcpHealthResult {
        return TcpHealthResult(config = config, endpoint = EndpointParser.parse(config), reachable = false, error = error)
    }

    companion object {
        const val DEFAULT_TIMEOUT_MS: Int = 1_500
        const val DEFAULT_CONCURRENCY: Int = 32
        const val DEFAULT_LIMIT: Int = 200
    }
}
