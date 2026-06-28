package org.mehdimt.v2rayfinder;

import android.app.Activity;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;
import org.mehdimt.v2rayfinder.runtime.NativeScanBridge;

public class MainActivity extends Activity {
    private EditText limitInput;
    private EditText timeoutInput;
    private CheckBox healthBox;
    private Button startButton;
    private TextView statusText;
    private TextView resultText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(buildUi());
    }

    private ScrollView buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(16), dp(16), dp(16));
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("V2Ray Finder — Native Kotlin");
        title.setTextSize(24);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        limitInput = new EditText(this);
        limitInput.setHint("Limit");
        limitInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        limitInput.setText("200");
        root.addView(limitInput);

        timeoutInput = new EditText(this);
        timeoutInput.setHint("Timeout seconds");
        timeoutInput.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        timeoutInput.setText("5");
        root.addView(timeoutInput);

        healthBox = new CheckBox(this);
        healthBox.setText("TCP health check");
        healthBox.setChecked(true);
        root.addView(healthBox);

        startButton = new Button(this);
        startButton.setText("Start native scan");
        startButton.setOnClickListener(v -> startScan());
        root.addView(startButton);

        statusText = new TextView(this);
        statusText.setText("Ready. Active scan path is native Kotlin.");
        statusText.setPadding(0, dp(12), 0, dp(12));
        root.addView(statusText);

        resultText = new TextView(this);
        resultText.setTextIsSelectable(true);
        root.addView(resultText);
        return scroll;
    }

    private void startScan() {
        startButton.setEnabled(false);
        statusText.setText("Running native Kotlin scan...");
        resultText.setText("");
        int limit = parseInt(limitInput.getText().toString(), 200);
        double timeout = parseDouble(timeoutInput.getText().toString(), 5.0);
        boolean health = healthBox.isChecked();
        new Thread(() -> {
            try {
                String json = NativeScanBridge.scan(this, limit, timeout, health, "");
                JSONObject payload = new JSONObject(json);
                runOnUiThread(() -> showResults(payload));
            } catch (Exception ex) {
                runOnUiThread(() -> showError(ex));
            }
        }).start();
    }

    private void showResults(JSONObject payload) {
        JSONObject stats = payload.optJSONObject("stats");
        JSONArray items = payload.optJSONArray("items");
        StringBuilder out = new StringBuilder();
        if (stats != null) {
            out.append("Fetched: ").append(stats.optInt("fetched", 0)).append('\n');
            out.append("Unique: ").append(stats.optInt("deduped", 0)).append('\n');
            out.append("Healthy: ").append(stats.optInt("healthy", 0)).append('\n');
            out.append("Scored: ").append(stats.optInt("scored", 0)).append('\n').append('\n');
        }
        if (items != null) {
            int shown = Math.min(items.length(), 50);
            for (int i = 0; i < shown; i++) {
                JSONObject item = items.optJSONObject(i);
                if (item == null) continue;
                out.append("#").append(i + 1).append(" ")
                        .append(item.optString("protocol", "?"))
                        .append(" score=").append(String.format(java.util.Locale.US, "%.1f", item.optDouble("total", 0.0)))
                        .append(" grade=").append(item.optString("grade", "?"))
                        .append('\n')
                        .append(item.optString("config", ""))
                        .append('\n').append('\n');
            }
        }
        resultText.setText(out.toString());
        statusText.setText("Done. Native Kotlin scan completed.");
        startButton.setEnabled(true);
    }

    private void showError(Exception ex) {
        statusText.setText("Native scan failed.");
        resultText.setText(ex.getClass().getSimpleName() + ": " + ex.getMessage());
        startButton.setEnabled(true);
    }

    private int parseInt(String value, int fallback) {
        try { return Integer.parseInt(value.trim()); } catch (Exception ignored) { return fallback; }
    }

    private double parseDouble(String value, double fallback) {
        try { return Double.parseDouble(value.trim()); } catch (Exception ignored) { return fallback; }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
