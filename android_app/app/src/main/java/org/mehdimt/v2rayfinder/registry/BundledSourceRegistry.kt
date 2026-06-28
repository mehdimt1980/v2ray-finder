package org.mehdimt.v2rayfinder.registry

import android.content.Context
import java.io.File

/**
 * Safe helper for loading a bundled or copied source registry JSON file.
 *
 * This class is not wired into the production scan path yet. It exists so Phase
 * 2 can compile and later phases can choose how to package/sync the registry
 * into Android assets or app-private files.
 */
class BundledSourceRegistry(private val context: Context) {
    fun loadFromAssets(assetName: String = DEFAULT_ASSET_NAME): List<SourceRecord> {
        val json = context.assets.open(assetName).bufferedReader(Charsets.UTF_8).use { it.readText() }
        return SourceRegistryParser.parseActive(json)
    }

    fun loadFromFile(file: File): List<SourceRecord> {
        val json = file.readText(Charsets.UTF_8)
        return SourceRegistryParser.parseActive(json)
    }

    companion object {
        const val DEFAULT_ASSET_NAME: String = "sources.json"
    }
}
