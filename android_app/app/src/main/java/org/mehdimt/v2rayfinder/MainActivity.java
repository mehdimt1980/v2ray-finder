package org.mehdimt.v2rayfinder;

import android.app.Activity;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public class MainActivity extends Activity {
    private final int bg = Color.rgb(8, 17, 31);
    private final int surface = Color.rgb(20, 29, 47);
    private final int surface2 = Color.rgb(30, 42, 65);
    private final int text = Color.rgb(236, 243, 255);
    private final int muted = Color.rgb(156, 173, 198);
    private final int accent = Color.rgb(48, 135, 246);
    private final int danger = Color.rgb(232, 70, 88);

    private EditText tokenInput;
    private EditText limitInput;
    private EditText timeoutInput;
    private CheckBox healthBox;
    private Button startButton;
    private Button copyButton;
    private ProgressBar progressBar;
    private TextView statusText;
    private TextView fetchedText;
    private TextView uniqueText;
    private TextView healthyText;
    private TextView scoredText;
    private LinearLayout resultList;
    private final List<String> latestConfigs = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(buildUi());
    }

    private View buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(bg);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(18), dp(16), dp(18));
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        scroll.addView(root);

        LinearLayout header = card();
        header.setOrientation(LinearLayout.VERTICAL);
        TextView title = label("V2Ray Finder", 30, text, true);
        TextView subtitle = label("Real v2ray_finder engine • Android", 14, muted, false);
        header.addView(title);
        header.addView(subtitle);
        root.addView(header, matchWrap());

        LinearLayout controls = card();
        controls.setOrientation(LinearLayout.VERTICAL);
        controls.setPadding(dp(14), dp(14), dp(14), dp(14));

        tokenInput = input("GitHub token optional", true);
        controls.addView(tokenInput, matchHeight(52));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(10), 0, dp(10));
        limitInput = input("Limit", false);
        limitInput.setText("200");
        limitInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        timeoutInput = input("Timeout", false);
        timeoutInput.setText("5");
        timeoutInput.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        row.addView(limitInput, weight());
        row.addView(space(dp(10), 1));
        row.addView(timeoutInput, weight());
        controls.addView(row);

        healthBox = new CheckBox(this);
        healthBox.setText("TCP health check");
        healthBox.setTextColor(text);
        healthBox.setTextSize(14);
        controls.addView(healthBox);

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setPadding(0, dp(10), 0, 0);
        startButton = button("Start Scan", accent);
        copyButton = button("Copy", surface2);
        copyButton.setEnabled(false);
        startButton.setOnClickListener(v -> startScan());
        copyButton.setOnClickListener(v -> copyResults());
        buttons.addView(startButton, weight());
        buttons.addView(space(dp(10), 1));
        buttons.addView(copyButton, weight());
        controls.addView(buttons);
        root.addView(controls, matchWrap());

        LinearLayout stats = new LinearLayout(this);
        stats.setOrientation(LinearLayout.HORIZONTAL);
        stats.setPadding(0, dp(12), 0, dp(12));
        fetchedText = statCard("Fetched", stats);
        uniqueText = statCard("Unique", stats);
        healthyText = statCard("Healthy", stats);
        scoredText = statCard("Scored", stats);
        root.addView(stats, matchWrap());

        LinearLayout statusCard = card();
        statusCard.setOrientation(LinearLayout.VERTICAL);
        statusText = label("Ready. Use a low limit first on Android.", 14, text, false);
        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setProgress(0);
        statusCard.addView(statusText);
        statusCard.addView(progressBar, matchHeight(18));
        root.addView(statusCard, matchWrap());

        resultList = new LinearLayout(this);
        resultList.setOrientation(LinearLayout.VERTICAL);
        resultList.setPadding(0, dp(12), 0, 0);
        root.addView(resultList, matchWrap());

        return scroll;
    }

    private void startScan() {
        latestConfigs.clear();
        resultList.removeAllViews();
        setStats("0", "0", "0", "0");
        setBusy(true);
        statusText.setText("Starting Python engine...");
        progressBar.setIndeterminate(true);

        int limit = parseInt(limitInput.getText().toString(), 200);
        double timeout = parseDouble(timeoutInput.getText().toString(), 5.0);
        boolean health = healthBox.isChecked();
        String token = tokenInput.getText().toString();

        new Thread(() -> {
            try {
                Python py = Python.getInstance();
                PyObject bridge = py.getModule("android_bridge");
                String json = bridge.callAttr("scan", limit, timeout, health, token).toString();
                JSONObject payload = new JSONObject(json);
                runOnUiThread(() -> showResults(payload));
            } catch (Exception ex) {
                runOnUiThread(() -> showError(ex));
            }
        }).start();
    }

    private void showResults(JSONObject payload) {
        try {
            JSONObject stats = payload.optJSONObject("stats");
            if (stats != null) {
                setStats(
                        String.valueOf(stats.optInt("fetched", 0)),
                        String.valueOf(stats.optInt("deduped", 0)),
                        String.valueOf(stats.optInt("healthy", 0)),
                        String.valueOf(stats.optInt("scored", 0))
                );
            }

            latestConfigs.clear();
            JSONArray configs = payload.optJSONArray("configs");
            if (configs != null) {
                for (int i = 0; i < configs.length(); i++) {
                    latestConfigs.add(configs.optString(i));
                }
            }

            JSONArray items = payload.optJSONArray("items");
            resultList.removeAllViews();
            if (items == null || items.length() == 0) {
                resultList.addView(resultRow("No scored results", "Try disabling health check or increasing the limit."));
            } else {
                for (int i = 0; i < Math.min(items.length(), 100); i++) {
                    JSONObject item = items.getJSONObject(i);
                    String line1 = String.format(Locale.US, "#%d  %s  •  %s  •  %.2f",
                            i + 1,
                            item.optString("protocol", "?").toUpperCase(Locale.US),
                            item.optString("grade", "?"),
                            item.optDouble("total", 0.0));
                    String line2 = item.optString("config", "");
                    resultList.addView(resultRow(line1, line2));
                }
            }
            statusText.setText("Done. " + latestConfigs.size() + " configs ready.");
            copyButton.setEnabled(!latestConfigs.isEmpty());
        } catch (Exception ex) {
            showError(ex);
            return;
        }
        setBusy(false);
    }

    private void showError(Exception ex) {
        statusText.setText("Error: " + ex.getMessage());
        resultList.addView(resultRow("Python error", String.valueOf(ex)));
        setBusy(false);
    }

    private void copyResults() {
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        cm.setPrimaryClip(ClipData.newPlainText("v2ray configs", String.join("\n", latestConfigs)));
        statusText.setText("Copied " + latestConfigs.size() + " configs.");
    }

    private void setBusy(boolean busy) {
        startButton.setEnabled(!busy);
        progressBar.setIndeterminate(busy);
        if (!busy) progressBar.setProgress(100);
    }

    private void setStats(String fetched, String unique, String healthy, String scored) {
        fetchedText.setText(fetched);
        uniqueText.setText(unique);
        healthyText.setText(healthy);
        scoredText.setText(scored);
    }

    private LinearLayout card() {
        LinearLayout layout = new LinearLayout(this);
        layout.setPadding(dp(14), dp(14), dp(14), dp(14));
        GradientDrawable bgDrawable = new GradientDrawable();
        bgDrawable.setColor(surface);
        bgDrawable.setCornerRadius(dp(18));
        layout.setBackground(bgDrawable);
        LinearLayout.LayoutParams lp = matchWrap();
        lp.setMargins(0, 0, 0, dp(12));
        layout.setLayoutParams(lp);
        return layout;
    }

    private TextView label(String value, int size, int color, boolean bold) {
        TextView tv = new TextView(this);
        tv.setText(value);
        tv.setTextSize(size);
        tv.setTextColor(color);
        tv.setGravity(Gravity.START);
        if (bold) tv.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return tv;
    }

    private EditText input(String hint, boolean password) {
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setHintTextColor(muted);
        input.setTextColor(text);
        input.setSingleLine(true);
        input.setTextSize(14);
        input.setPadding(dp(12), 0, dp(12), 0);
        input.setInputType(password ? (InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD) : InputType.TYPE_CLASS_TEXT);
        GradientDrawable bgDrawable = new GradientDrawable();
        bgDrawable.setColor(surface2);
        bgDrawable.setCornerRadius(dp(12));
        input.setBackground(bgDrawable);
        return input;
    }

    private Button button(String title, int color) {
        Button btn = new Button(this);
        btn.setText(title);
        btn.setTextColor(text);
        btn.setTextSize(14);
        btn.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        GradientDrawable bgDrawable = new GradientDrawable();
        bgDrawable.setColor(color);
        bgDrawable.setCornerRadius(dp(12));
        btn.setBackground(bgDrawable);
        return btn;
    }

    private TextView statCard(String title, LinearLayout parent) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(10), dp(8), dp(10), dp(8));
        GradientDrawable bgDrawable = new GradientDrawable();
        bgDrawable.setColor(surface);
        bgDrawable.setCornerRadius(dp(14));
        card.setBackground(bgDrawable);

        TextView top = label(title.toUpperCase(Locale.US), 10, muted, false);
        TextView value = label("0", 20, text, true);
        card.addView(top);
        card.addView(value);
        LinearLayout.LayoutParams lp = weight();
        lp.setMargins(dp(3), 0, dp(3), 0);
        parent.addView(card, lp);
        return value;
    }

    private View resultRow(String line1, String line2) {
        LinearLayout row = card();
        row.setOrientation(LinearLayout.VERTICAL);
        TextView a = label(line1, 14, text, true);
        TextView b = label(line2, 11, muted, false);
        b.setMaxLines(3);
        row.addView(a);
        row.addView(b);
        return row;
    }

    private View space(int width, int height) {
        View v = new View(this);
        v.setLayoutParams(new LinearLayout.LayoutParams(width, height));
        return v;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams matchHeight(int height) {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(height));
    }

    private LinearLayout.LayoutParams weight() {
        return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private int dp(int value) {
        float density = getResources().getDisplayMetrics().density;
        return Math.round(value * density);
    }

    private int parseInt(String value, int fallback) {
        try { return Integer.parseInt(value.trim()); } catch (Exception ignored) { return fallback; }
    }

    private double parseDouble(String value, double fallback) {
        try { return Double.parseDouble(value.trim()); } catch (Exception ignored) { return fallback; }
    }
}
