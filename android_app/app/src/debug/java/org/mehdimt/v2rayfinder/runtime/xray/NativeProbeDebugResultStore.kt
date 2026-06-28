package org.mehdimt.v2rayfinder.runtime.xray

import android.content.Context
import java.io.File

/** Debug-build-only storage for native probe JSON results. */
class NativeProbeDebugResultStore(private val context: Context) {
    fun writeLatest(json: String): File {
        val dir = resultDir()
        val latest = File(dir, FILE_NAME)
        latest.writeText(json, Charsets.UTF_8)
        File(dir, historyFileName()).writeText(json, Charsets.UTF_8)
        return latest
    }

    fun latestFile(): File = File(resultDir(), FILE_NAME)

    fun historyDir(): File = resultDir()

    private fun resultDir(): File {
        val dir = File(context.filesDir, DIR_NAME)
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    private fun historyFileName(): String = "result-" + System.currentTimeMillis().toString() + ".json"

    companion object {
        const val DIR_NAME: String = "native-probe-debug"
        const val FILE_NAME: String = "latest-result.json"
    }
}
