package org.mehdimt.v2rayfinder.kotlinmigration

/**
 * Compile-time marker for the Kotlin migration path.
 *
 * This class is intentionally not wired into the runtime UI yet. Its purpose is
 * to verify that the Android module can compile Kotlin beside the existing
 * Java + Chaquopy implementation without changing app behavior.
 */
object KotlinRuntimeMarker {
    const val PHASE: String = "phase-1-kotlin-skeleton"

    fun isAvailable(): Boolean = PHASE.isNotBlank()
}
