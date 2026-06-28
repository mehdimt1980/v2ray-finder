package org.mehdimt.v2rayfinder.runtime.xray

import android.content.Context
import java.io.File

/** Debug-build-only storage for the latest native probe JSON result. */
class NativeProbeDebugResultStore(private val context: Context) {
    fun writeLatest(json: String): File {
        val dir = File(context.filesDir, DIR_NAME)
        if (!dir.exists()) dir.mkdirs()
        val file = File(dir, FILE_NAME)
        file.writeText(json, Charsets.UTF_8)
        return file
    }

    fun latestFile(): File = File(File(context.filesDir, DIR_NAME), FILE_NAME)

    companion object {
        const val DIR_NAME: String = "native-probe-debug"
        const val FILE_NAME: String = "latest-result.json"
    }
}
