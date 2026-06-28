package org.mehdimt.v2rayfinder.runtime

import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Minimal native fetcher for Phase 3.
 *
 * It is deliberately synchronous and not wired into the UI yet. Later phases can
 * wrap it in coroutines or a worker layer after compile/runtime behavior is
 * verified.
 */
class SourceFetcher(
    private val connectTimeoutMs: Int = DEFAULT_TIMEOUT_MS,
    private val readTimeoutMs: Int = DEFAULT_TIMEOUT_MS,
) {
    fun fetch(url: String): FetchResult {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = connectTimeoutMs
                readTimeout = readTimeoutMs
                instanceFollowRedirects = true
                setRequestProperty("User-Agent", USER_AGENT)
                setRequestProperty("Accept", "text/plain, text/yaml, application/json, */*")
            }

            val status = connection.responseCode
            val stream = if (status in 200..399) connection.inputStream else connection.errorStream
            val body = stream?.use { input ->
                BufferedReader(InputStreamReader(input, Charsets.UTF_8)).use { reader ->
                    reader.readText()
                }
            } ?: ""

            FetchResult(
                url = url,
                ok = status in 200..399 && body.isNotBlank(),
                statusCode = status,
                body = body,
                error = if (status in 200..399) "" else "HTTP $status",
            )
        } catch (exc: Exception) {
            FetchResult(url = url, ok = false, error = exc.message ?: exc.javaClass.simpleName)
        } finally {
            connection?.disconnect()
        }
    }

    companion object {
        const val DEFAULT_TIMEOUT_MS: Int = 12_000
        const val USER_AGENT: String = "v2ray-finder-android-kotlin/phase-3"
    }
}
