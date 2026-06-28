package org.mehdimt.v2rayfinder.runtime.xray

import android.app.Activity
import android.os.Bundle
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class NativeProbeDebugActivity : Activity() {
    private lateinit var input: EditText
    private lateinit var output: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        input = EditText(this).apply {
            hint = "Paste one config URI"
            minLines = 4
            setSingleLine(false)
        }
        output = TextView(this).apply {
            text = "Native debug probe is idle."
            setTextIsSelectable(true)
        }
        val runButton = Button(this).apply {
            text = "Run native probe"
            setOnClickListener { runProbe() }
        }
        val diagnosticsButton = Button(this).apply {
            text = "Diagnostics"
            setOnClickListener { output.text = NativeValidationDebugHook(this@NativeProbeDebugActivity).diagnosticsJson() }
        }
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
            addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(runButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(diagnosticsButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(output, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        setContentView(ScrollView(this).apply { addView(layout) })
        readIntentExtras()
    }

    private fun readIntentExtras() {
        val config = intent?.getStringExtra(EXTRA_CONFIG)?.trim().orEmpty()
        if (config.isNotBlank()) input.setText(config)
        if (config.isNotBlank() && intent?.getBooleanExtra(EXTRA_AUTO_RUN, false) == true) runProbe()
    }

    private fun runProbe() {
        val config = input.text?.toString()?.trim().orEmpty()
        if (config.isBlank()) {
            output.text = "No config provided."
            return
        }
        output.text = "Running..."
        Thread {
            val result = NativeValidationDebugHook(this).runSingleConfig(config)
            val store = NativeProbeDebugResultStore(this)
            val saved = store.writeLatest(result)
            val text = result + "\n\nLatest:\n" + saved.absolutePath + "\n\nHistory dir:\n" + store.historyDir().absolutePath
            runOnUiThread { output.text = text }
        }.start()
    }

    companion object {
        const val EXTRA_CONFIG: String = "config"
        const val EXTRA_AUTO_RUN: String = "auto_run"
    }
}
