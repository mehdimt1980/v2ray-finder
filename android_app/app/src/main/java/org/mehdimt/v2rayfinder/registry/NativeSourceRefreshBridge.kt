package org.mehdimt.v2rayfinder.registry

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

object NativeSourceRefreshBridge {
    private const val REGISTRY_URL: String = "https://raw.githubusercontent.com/mehdimt1980/v2ray-finder/main/registry/sources.json"
    private const val CACHE_DIR: String = "source-registry"
    private const val CACHE_FILE: String = "sources.json"
    private const val MAX_CACHE_AGE_MS: Long = 6L * 60L * 60L * 1000L

    @JvmStatic
    fun ensureFreshRegistry(context: Context, token: String = ""): String {
        val cache = cachedRegistryFile(context)
        val fresh = cache.isFile && System.currentTimeMillis() - cache.lastModified() <= MAX_CACHE_AGE_MS
        val hasHunterTiers = try {
            BundledSourceRegistry(context).loadFromFile(cache).map { it.hunterTier }.toSet()
                .containsAll(setOf("ELITE", "STABLE", "FRESH"))
        } catch (_: Exception) {
            false
        }
        if (fresh && hasHunterTiers) return JSONObject().put("ok", true).put("message", "registry_cache_fresh").toString()
        return refreshSourcesNow(context, token)
    }

    @JvmStatic
    fun refreshSourcesNow(context: Context, token: String): String {
        return try {
            val connection = (URL(REGISTRY_URL).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 15_000
                readTimeout = 15_000
                setRequestProperty("User-Agent", "v2ray-finder-android-native/registry-refresh")
                if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token")
            }
            val status = connection.responseCode
            val body = if (status in 200..399) {
                connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            } else {
                ""
            }
            connection.disconnect()
            if (status !in 200..399 || body.isBlank()) {
                return JSONObject()
                    .put("ok", false)
                    .put("active_sources", activeSourceCount(context))
                    .put("message", "دریافت registry ناموفق بود: HTTP $status")
                    .toString()
            }
            val active = SourceRegistryParser.parseActive(body)
            if (active.isEmpty()) {
                return JSONObject()
                    .put("ok", false)
                    .put("active_sources", activeSourceCount(context))
                    .put("message", "registry دریافت شد، اما منبع trusted/official فعالی نداشت")
                    .toString()
            }
            val file = cachedRegistryFile(context)
            file.parentFile?.mkdirs()
            file.writeText(body, Charsets.UTF_8)
            JSONObject()
                .put("ok", true)
                .put("active_sources", active.size)
                .put("message", "منابع به‌روزرسانی شد")
                .put("path", file.absolutePath)
                .toString()
        } catch (exc: Exception) {
            JSONObject()
                .put("ok", false)
                .put("active_sources", activeSourceCount(context))
                .put("message", "به‌روزرسانی منابع ناموفق بود: ${exc.message ?: exc.javaClass.simpleName}")
                .toString()
        }
    }

    @JvmStatic
    fun cachedRegistryFile(context: Context): File = File(File(context.filesDir, CACHE_DIR), CACHE_FILE)

    @JvmStatic
    fun activeSourceCount(context: Context): Int = try {
        val cache = cachedRegistryFile(context)
        if (cache.isFile) BundledSourceRegistry(context).loadFromFile(cache).size else BundledSourceRegistry(context).loadFromAssets().size
    } catch (_: Exception) {
        0
    }
}
