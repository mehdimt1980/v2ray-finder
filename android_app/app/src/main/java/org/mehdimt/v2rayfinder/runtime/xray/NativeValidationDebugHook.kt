package org.mehdimt.v2rayfinder.runtime.xray

import android.content.Context
import org.json.JSONObject
import java.io.File

/**
 * Android-side debug hook for the native Kotlin validation path.
 *
 * This hook is intentionally not referenced by MainActivity. It gives future
 * debug UI or instrumentation tests a safe way to locate the bundled xray binary
 * and run one explicit native validation check.
 */
class NativeValidationDebugHook(
    private val context: Context,
    private val adapter: NativeValidationDebugAdapter = NativeValidationDebugAdapter(),
) {
    fun isAvailable(): Boolean = binaryFile().isFile

    fun diagnosticsJson(): String = JSONObject()
        .put("available", isAvailable())
        .put("binary_path", binaryFile().absolutePath)
        .put("work_dir", workDir().absolutePath)
        .toString()

    fun runSingleConfig(config: String): String {
        val binary = binaryFile()
        if (!binary.isFile) {
            return JSONObject()
                .put("engine", "kotlin_native_debug")
                .put("validation_ok", false)
                .put("error", "xray_binary_not_found")
                .put("binary_path", binary.absolutePath)
                .toString()
        }
        val dir = workDir()
        if (!dir.exists()) dir.mkdirs()
        return adapter.validateToJson(
            config = config,
            binaryPath = binary.absolutePath,
            workDir = dir,
        )
    }

    private fun binaryFile(): File {
        val nativeDir = context.applicationInfo.nativeLibraryDir ?: ""
        return File(nativeDir, "libxray.so")
    }

    private fun workDir(): File = File(context.filesDir, "kotlin-native-validation")
}
