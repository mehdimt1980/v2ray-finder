package org.mehdimt.v2rayfinder.runtime.xray

import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket

object PortUtils {
    fun findFreePort(): Int = ServerSocket(0).use { it.localPort }

    fun waitForPort(host: String, port: Int, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (canConnect(host, port, 250)) return true
            try {
                Thread.sleep(100)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                return false
            }
        }
        return false
    }

    private fun canConnect(host: String, port: Int, timeoutMs: Int): Boolean = try {
        Socket().use { socket ->
            socket.connect(InetSocketAddress(host, port), timeoutMs)
        }
        true
    } catch (_: Exception) {
        false
    }
}
