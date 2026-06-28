package org.mehdimt.v2rayfinder.runtime

/** Stable order-preserving config deduplication. */
object ConfigDeduplicator {
    fun deduplicate(configs: Iterable<String>): List<String> {
        val seen = linkedSetOf<String>()
        val out = mutableListOf<String>()
        for (config in configs) {
            val normalized = normalize(config)
            if (normalized.isNotBlank() && seen.add(normalized)) {
                out += normalized
            }
        }
        return out
    }

    fun normalize(config: String): String =
        config.trim()
            .trimEnd(',', ';')
            .replace("\\u003d", "=")
            .replace("\\u0026", "&")
}
