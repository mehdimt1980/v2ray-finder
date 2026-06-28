package org.mehdimt.v2rayfinder.registry

import org.json.JSONArray
import org.json.JSONObject

/**
 * Minimal JSON parser for registry/sources.json.
 *
 * This parser is deliberately strict about required runtime fields (url must be
 * present) but tolerant about optional metadata and future hunter-added fields.
 */
object SourceRegistryParser {
    fun parse(json: String): List<SourceRecord> {
        val root = JSONArray(json)
        val records = mutableListOf<SourceRecord>()
        val seenUrls = linkedSetOf<String>()

        for (index in 0 until root.length()) {
            val item = root.optJSONObject(index) ?: continue
            val record = item.toSourceRecordOrNull() ?: continue
            if (record.url.isBlank() || !seenUrls.add(record.url)) continue
            records += record
        }

        return records
    }

    fun active(records: List<SourceRecord>): List<SourceRecord> =
        records.filter { it.isActive }

    fun parseActive(json: String): List<SourceRecord> = active(parse(json))

    private fun JSONObject.toSourceRecordOrNull(): SourceRecord? {
        val url = optString("url", "").trim()
        if (url.isBlank()) return null

        val label = optString("label", "").trim().ifBlank { url }
        val id = optString("id", "").trim().ifBlank { makeStableId(label) }
        val status = optString("status", "candidate").trim().lowercase()

        return SourceRecord(
            id = id,
            label = label,
            url = url,
            sourceType = optString("source_type", "static_subscription").trim(),
            trust = optString("trust", "low").trim().lowercase(),
            status = status,
            enabled = optBoolean("enabled", true),
            tags = optStringList("tags"),
            protocols = optStringList("protocols").map { it.lowercase() },
            notes = optString("notes", "").trim(),
            region = optString("region", "").trim(),
            addedAt = optString("added_at", "").trim(),
            lastReviewedAt = optString("last_reviewed_at", "").trim(),
            upstreamUrl = optString("upstream_url", "").trim(),
        )
    }

    private fun JSONObject.optStringList(name: String): List<String> {
        val array = optJSONArray(name) ?: return emptyList()
        val values = mutableListOf<String>()
        val seen = linkedSetOf<String>()
        for (i in 0 until array.length()) {
            val value = array.optString(i, "").trim()
            if (value.isNotEmpty() && seen.add(value)) values += value
        }
        return values
    }

    private fun makeStableId(value: String): String =
        value.lowercase()
            .replace(Regex("[^a-z0-9]+"), "-")
            .trim('-')
            .take(80)
            .ifBlank { "source" }
}
