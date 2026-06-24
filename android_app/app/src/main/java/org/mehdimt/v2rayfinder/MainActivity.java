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
    private static final int PAGE_SIZE = 10;

    private final int bg = Color.rgb(7, 12, 27);
    private final int surface = Color.rgb(19, 29, 51);
    private final int surface2 = Color.rgb(33, 47, 82);
    private final int surface3 = Color.rgb(24, 39, 71);
    private final int text = Color.rgb(241, 246, 255);
    private final int muted = Color.rgb(160, 178, 205);
    private final int accent = Color.rgb(17, 145, 255);
    private final int warning = Color.rgb(255, 184, 77);

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
    private JSONArray currentItems = new JSONArray();
    private JSONArray currentFailedSources = new JSONArray();
    private int currentPage = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(bg);
        getWindow().setNavigationBarColor(bg);
        setContentView(buildUi());
    }

    private View buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(bg);
        scroll.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(18), dp(16), dp(18));
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        scroll.addView(root);

        LinearLayout header = card(surface3, 22);
        header.setOrientation(LinearLayout.VERTICAL);
        TextView title = label("V2Ray Finder", 30, text, true, false);
        TextView subtitle = label("یابنده هوشمند کانفیگ‌های V2Ray برای کاربران ایران", 14, muted, false, true);
        TextView hint = label("اسکن، ارزیابی سلامت و کپی سریع سرورها", 12, muted, false, true);
        header.addView(title);
        header.addView(subtitle);
        header.addView(hint);
        root.addView(header, matchWrap());

        LinearLayout controls = card(surface, 22);
        controls.setOrientation(LinearLayout.VERTICAL);
        controls.setPadding(dp(14), dp(14), dp(14), dp(14));

        tokenInput = input("توکن گیت‌هاب (اختیاری)", true, true);
        controls.addView(tokenInput, matchHeight(54));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(12), 0, dp(8));
        row.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        limitInput = input("۲۰۰", false, false);
        limitInput.setText("200");
        limitInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        timeoutInput = input("۵", false, false);
        timeoutInput.setText("5");
        timeoutInput.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);

        row.addView(inputGroup("تعداد کانفیگ‌ها", "حداکثر تعداد برای بررسی", limitInput), weight());
        row.addView(space(dp(10), 1));
        row.addView(inputGroup("مهلت اتصال", "ثانیه برای هر سرور", timeoutInput), weight());
        controls.addView(row);

        TextView help = label("پیشنهاد: ۲۰۰ کانفیگ و ۵ ثانیه برای شروع مناسب است.", 12, muted, false, true);
        help.setPadding(0, 0, 0, dp(6));
        controls.addView(help);

        healthBox = new CheckBox(this);
        healthBox.setText("بررسی سلامت TCP");
        healthBox.setTextColor(text);
        healthBox.setTextSize(14);
        healthBox.setGravity(Gravity.RIGHT | Gravity.CENTER_VERTICAL);
        healthBox.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        controls.addView(healthBox);

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setPadding(0, dp(10), 0, 0);
        buttons.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        startButton = button("شروع اسکن", accent);
        copyButton = button("کپی همه", surface2);
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
        stats.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        fetchedText = statCard("دریافتی", stats);
        uniqueText = statCard("یکتا", stats);
        healthyText = statCard("سالم", stats);
        scoredText = statCard("رتبه‌بندی", stats);
        root.addView(stats, matchWrap());

        LinearLayout statusCard = card(surface, 18);
        statusCard.setOrientation(LinearLayout.VERTICAL);
        statusText = label("آماده است. برای شروع، تعداد ۲۰۰ انتخاب خوبی است.", 14, text, false, true);
        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setProgress(0);
        statusCard.addView(statusText);
        statusCard.addView(progressBar, matchHeight(14));
        root.addView(statusCard, matchWrap());

        resultList = new LinearLayout(this);
        resultList.setOrientation(LinearLayout.VERTICAL);
        resultList.setPadding(0, dp(12), 0, 0);
        resultList.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        root.addView(resultList, matchWrap());

        return scroll;
    }

    private void startScan() {
        latestConfigs.clear();
        currentItems = new JSONArray();
        currentFailedSources = new JSONArray();
        currentPage = 0;
        resultList.removeAllViews();
        setStats("0", "0", "0", "0");
        setBusy(true);
        statusText.setText("در حال راه‌اندازی موتور پایتون...");
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
            JSONArray failedSources = payload.optJSONArray("failed_sources");
            currentItems = items == null ? new JSONArray() : items;
            currentFailedSources = failedSources == null ? new JSONArray() : failedSources;
            currentPage = 0;

            renderCurrentPage();

            String done = "تمام شد. " + latestConfigs.size() + " کانفیگ آماده است.";
            if (currentFailedSources.length() > 0) {
                done += " " + currentFailedSources.length() + " منبع ناموفق هم ثبت شد.";
            }
            statusText.setText(done);
            copyButton.setEnabled(!latestConfigs.isEmpty());
        } catch (Exception ex) {
            showError(ex);
            return;
        }
        setBusy(false);
    }

    private void renderCurrentPage() {
        resultList.removeAllViews();
        int totalItems = currentItems.length();
        int pageCount = Math.max(1, (int) Math.ceil(totalItems / (double) PAGE_SIZE));
        if (currentPage < 0) currentPage = 0;
        if (currentPage >= pageCount) currentPage = pageCount - 1;

        if (totalItems == 0) {
            resultList.addView(resultRow("نتیجه‌ای پیدا نشد", "بررسی سلامت را خاموش کن یا تعداد نتایج را بیشتر کن.", "", false));
            renderFailedSourcesIfNeeded(true);
            return;
        }

        int start = currentPage * PAGE_SIZE;
        int end = Math.min(start + PAGE_SIZE, totalItems);

        resultList.addView(sectionTitle("بهترین کانفیگ‌ها — صفحه " + (currentPage + 1) + " از " + pageCount));
        resultList.addView(infoRow("نمایش صفحه‌ای", "کانفیگ‌های " + (start + 1) + " تا " + end + " از " + totalItems + " مورد"));
        resultList.addView(pagerRow(pageCount));

        for (int i = start; i < end; i++) {
            try {
                JSONObject item = currentItems.getJSONObject(i);
                String protocol = item.optString("protocol", "?").toUpperCase(Locale.US);
                String grade = item.optString("grade", "?");
                double score = item.optDouble("total", 0.0);
                String latency = item.isNull("latency_ms") ? "نامشخص" : String.format(Locale.US, "%.0f ms", item.optDouble("latency_ms", 0.0));
                String title = "#" + (i + 1) + "  " + protocol + "  •  کیفیت " + grade + "  •  امتیاز " + String.format(Locale.US, "%.2f", score);
                String meta = "تاخیر: " + latency;
                String config = item.optString("config", "");
                resultList.addView(resultRow(title, meta, config, true));
            } catch (Exception ignored) {
                // Skip malformed rows without breaking the whole page.
            }
        }

        resultList.addView(pagerRow(pageCount));
        renderFailedSourcesIfNeeded(currentPage == pageCount - 1);
        statusText.setText("صفحه " + (currentPage + 1) + " از " + pageCount + " — " + latestConfigs.size() + " کانفیگ آماده است.");
    }

    private void renderFailedSourcesIfNeeded(boolean shouldShow) {
        int failedCount = currentFailedSources.length();
        if (!shouldShow || failedCount == 0) return;

        int shownFailed = Math.min(failedCount, 20);
        resultList.addView(sectionTitle("منابع ناموفق — " + failedCount + " مورد"));
        resultList.addView(infoRow("چرا این مهم است؟", "اگر GitHub محدودیت بدهد، یک لینک timeout شود یا منبعی خراب باشد، اینجا دلیلش را می‌بینی."));
        for (int i = 0; i < shownFailed; i++) {
            try {
                JSONObject failed = currentFailedSources.getJSONObject(i);
                resultList.addView(failedSourceRow(failed));
            } catch (Exception ignored) {
                // Skip malformed error rows.
            }
        }
        if (failedCount > shownFailed) {
            resultList.addView(infoRow("نمایش محدود", "برای خوانایی، فقط ۲۰ منبع ناموفق اول نشان داده شد."));
        }
    }

    private View pagerRow(int pageCount) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(4), 0, dp(10));
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        Button next = button("بعدی", accent);
        Button previous = button("قبلی", surface2);
        TextView page = label("صفحه " + (currentPage + 1) + " / " + pageCount, 13, text, true, true);
        page.setGravity(Gravity.CENTER);

        previous.setEnabled(currentPage > 0);
        next.setEnabled(currentPage < pageCount - 1);
        previous.setOnClickListener(v -> {
            if (currentPage > 0) {
                currentPage--;
                renderCurrentPage();
            }
        });
        next.setOnClickListener(v -> {
            if (currentPage < pageCount - 1) {
                currentPage++;
                renderCurrentPage();
            }
        });

        row.addView(next, weight());
        row.addView(space(dp(8), 1));
        row.addView(page, weight());
        row.addView(space(dp(8), 1));
        row.addView(previous, weight());
        return row;
    }

    private void showError(Exception ex) {
        statusText.setText("خطا: " + ex.getMessage());
        resultList.addView(resultRow("خطای موتور پایتون", String.valueOf(ex), "", false));
        setBusy(false);
    }

    private void copyResults() {
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        cm.setPrimaryClip(ClipData.newPlainText("v2ray configs", String.join("\n", latestConfigs)));
        statusText.setText(latestConfigs.size() + " کانفیگ کپی شد.");
    }

    private void copyOne(String config) {
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        cm.setPrimaryClip(ClipData.newPlainText("v2ray config", config));
        statusText.setText("یک کانفیگ کپی شد.");
    }

    private void setBusy(boolean busy) {
        startButton.setEnabled(!busy);
        startButton.setText(busy ? "در حال اسکن..." : "شروع اسکن");
        progressBar.setIndeterminate(busy);
        if (!busy) progressBar.setProgress(100);
    }

    private void setStats(String fetched, String unique, String healthy, String scored) {
        fetchedText.setText(fetched);
        uniqueText.setText(unique);
        healthyText.setText(healthy);
        scoredText.setText(scored);
    }

    private LinearLayout card(int color, int radius) {
        LinearLayout layout = new LinearLayout(this);
        layout.setPadding(dp(14), dp(14), dp(14), dp(14));
        layout.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        GradientDrawable bgDrawable = new GradientDrawable();
        bgDrawable.setColor(color);
        bgDrawable.setCornerRadius(dp(radius));
        layout.setBackground(bgDrawable);
        LinearLayout.LayoutParams lp = matchWrap();
        lp.setMargins(0, 0, 0, dp(12));
        layout.setLayoutParams(lp);
        return layout;
    }

    private TextView label(String value, int size, int color, boolean bold, boolean rtl) {
        TextView tv = new TextView(this);
        tv.setText(value);
        tv.setTextSize(size);
        tv.setTextColor(color);
        tv.setGravity(rtl ? Gravity.RIGHT : Gravity.LEFT);
        tv.setTextDirection(rtl ? View.TEXT_DIRECTION_RTL : View.TEXT_DIRECTION_LTR);
        if (bold) tv.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return tv;
    }

    private LinearLayout inputGroup(String title, String description, EditText input) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        group.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        TextView titleView = label(title, 13, text, true, true);
        TextView descView = label(description, 10, muted, false, true);
        descView.setPadding(0, 0, 0, dp(6));

        group.addView(titleView);
        group.addView(descView);
        group.addView(input, matchHeight(46));
        return group;
    }

    private EditText input(String hint, boolean password, boolean rtl) {
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setHintTextColor(muted);
        input.setTextColor(text);
        input.setSingleLine(true);
        input.setTextSize(14);
        input.setPadding(dp(12), 0, dp(12), 0);
        input.setGravity(rtl ? Gravity.RIGHT | Gravity.CENTER_VERTICAL : Gravity.LEFT | Gravity.CENTER_VERTICAL);
        input.setTextDirection(rtl ? View.TEXT_DIRECTION_RTL : View.TEXT_DIRECTION_LTR);
        input.setInputType(password ? (InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD) : InputType.TYPE_CLASS_TEXT);
        GradientDrawable bgDrawable = new GradientDrawable();
        bgDrawable.setColor(surface2);
        bgDrawable.setCornerRadius(dp(14));
        input.setBackground(bgDrawable);
        return input;
    }

    private Button button(String title, int color) {
        Button btn = new Button(this);
        btn.setText(title);
        btn.setAllCaps(false);
        btn.setTextColor(text);
        btn.setTextSize(14);
        btn.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        GradientDrawable bgDrawable = new GradientDrawable();
        bgDrawable.setColor(color);
        bgDrawable.setCornerRadius(dp(14));
        btn.setBackground(bgDrawable);
        return btn;
    }

    private TextView statCard(String title, LinearLayout parent) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(10), dp(8), dp(10), dp(8));
        card.setGravity(Gravity.RIGHT);
        GradientDrawable bgDrawable = new GradientDrawable();
        bgDrawable.setColor(surface);
        bgDrawable.setCornerRadius(dp(16));
        card.setBackground(bgDrawable);

        TextView top = label(title, 10, muted, false, true);
        TextView value = label("0", 20, text, true, false);
        card.addView(top);
        card.addView(value);
        LinearLayout.LayoutParams lp = weight();
        lp.setMargins(dp(3), 0, dp(3), 0);
        parent.addView(card, lp);
        return value;
    }

    private View sectionTitle(String value) {
        TextView tv = label(value, 15, text, true, true);
        tv.setPadding(dp(2), 0, dp(2), dp(10));
        return tv;
    }

    private View resultRow(String line1, String line2, String config, boolean canCopy) {
        LinearLayout row = card(surface, 18);
        row.setOrientation(LinearLayout.VERTICAL);

        TextView a = label(line1, 14, text, true, true);
        TextView b = label(line2, 12, muted, false, true);
        row.addView(a);
        row.addView(b);

        if (config != null && !config.isEmpty()) {
            TextView cfg = label(config, 10, muted, false, false);
            cfg.setTypeface(Typeface.MONOSPACE);
            cfg.setMaxLines(3);
            cfg.setPadding(0, dp(8), 0, dp(4));
            row.addView(cfg);
        }

        if (canCopy && config != null && !config.isEmpty()) {
            Button copy = button("کپی این کانفیگ", surface2);
            copy.setOnClickListener(v -> copyOne(config));
            LinearLayout.LayoutParams lp = matchHeight(42);
            lp.setMargins(0, dp(8), 0, 0);
            row.addView(copy, lp);
        }
        return row;
    }

    private View infoRow(String title, String body) {
        LinearLayout row = card(surface3, 18);
        row.setOrientation(LinearLayout.VERTICAL);
        row.addView(label(title, 13, text, true, true));
        row.addView(label(body, 12, muted, false, true));
        return row;
    }

    private View failedSourceRow(JSONObject failed) {
        LinearLayout row = card(surface3, 18);
        row.setOrientation(LinearLayout.VERTICAL);

        String errorType = failed.optString("error_type", "unknown_error");
        String message = failed.optString("message", "خطای نامشخص");
        String url = failed.optString("url", "");
        JSONObject details = failed.optJSONObject("details");

        TextView title = label(friendlyErrorType(errorType), 14, warning, true, true);
        TextView msg = label(shortMessage(message), 12, text, false, true);
        TextView hint = label(errorHint(errorType), 11, muted, false, true);
        TextView source = label(shortUrl(url), 10, muted, false, false);
        source.setTypeface(Typeface.MONOSPACE);
        source.setMaxLines(2);
        source.setPadding(0, dp(6), 0, 0);

        row.addView(title);
        row.addView(msg);
        row.addView(hint);
        row.addView(source);

        if (details != null && details.length() > 0) {
            TextView detailView = label("جزئیات: " + details.toString(), 10, muted, false, false);
            detailView.setTypeface(Typeface.MONOSPACE);
            detailView.setMaxLines(2);
            row.addView(detailView);
        }
        return row;
    }

    private String friendlyErrorType(String errorType) {
        if (errorType == null) return "خطای نامشخص";
        if (errorType.contains("rate_limit")) return "محدودیت GitHub / Rate Limit";
        if (errorType.contains("timeout")) return "پایان مهلت اتصال";
        if (errorType.contains("network")) return "خطای شبکه";
        if (errorType.contains("authentication")) return "خطای توکن یا دسترسی";
        if (errorType.contains("github")) return "خطای GitHub";
        if (errorType.contains("http")) return "خطای HTTP";
        return "خطای منبع";
    }

    private String errorHint(String errorType) {
        if (errorType == null) return "این منبع فعلاً قابل استفاده نبود.";
        if (errorType.contains("rate_limit")) return "پیشنهاد: توکن GitHub وارد کن یا کمی بعد دوباره امتحان کن.";
        if (errorType.contains("timeout")) return "پیشنهاد: مهلت اتصال را بیشتر کن یا بعداً دوباره تست کن.";
        if (errorType.contains("network")) return "پیشنهاد: اینترنت، DNS یا دسترسی به GitHub را بررسی کن.";
        if (errorType.contains("authentication")) return "پیشنهاد: توکن GitHub را بررسی یا خالی کن.";
        return "این خطا فقط روی همین منبع اثر دارد؛ نتایج سالم همچنان قابل استفاده‌اند.";
    }

    private String shortMessage(String message) {
        if (message == null || message.trim().isEmpty()) return "پیام خطا موجود نیست.";
        String m = message.replace('\n', ' ').trim();
        return m.length() > 140 ? m.substring(0, 140) + "…" : m;
    }

    private String shortUrl(String url) {
        if (url == null || url.trim().isEmpty()) return "source: unknown";
        return url.length() > 120 ? url.substring(0, 120) + "…" : url;
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
