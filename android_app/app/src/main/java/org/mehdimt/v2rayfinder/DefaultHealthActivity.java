package org.mehdimt.v2rayfinder;

import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import org.json.JSONObject;

import java.io.File;
import java.lang.reflect.Method;

/**
 * Launcher activity that keeps the MainActivity UI mostly unchanged, enables
 * TCP health checking by default, and adds optional registry / xray controls.
 */
public class DefaultHealthActivity extends MainActivity {
    private final int text = Color.rgb(241, 246, 255);
    private final int muted = Color.rgb(160, 178, 205);
    private final int accent = Color.rgb(91, 192, 255);

    private CheckBox realCheckBox;
    private String xrayBinaryPath = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        xrayBinaryPath = prepareXrayBinary();
        View root = getWindow().getDecorView();
        enableHealthCheckByDefault(root);
        addRealCheckOption(root);
        installStartHook(root);
    }

    private void enableHealthCheckByDefault(View view) {
        if (view instanceof CheckBox) {
            CheckBox checkBox = (CheckBox) view;
            CharSequence label = checkBox.getText();
            if (label != null && label.toString().contains("بررسی سلامت TCP")) {
                checkBox.setChecked(true);
                return;
            }
        }

        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                enableHealthCheckByDefault(group.getChildAt(i));
            }
        }
    }

    private void addRealCheckOption(View view) {
        if (view instanceof CheckBox) {
            CheckBox health = (CheckBox) view;
            CharSequence label = health.getText();
            if (label != null && label.toString().contains("بررسی سلامت TCP")) {
                ViewGroup parent = (ViewGroup) health.getParent();
                int index = parent.indexOfChild(health);
                realCheckBox = new CheckBox(this);
                realCheckBox.setText("Real Validation v2 با xray — کندتر، دقیق‌تر");
                realCheckBox.setTextColor(text);
                realCheckBox.setTextSize(14);
                realCheckBox.setGravity(Gravity.RIGHT | Gravity.CENTER_VERTICAL);
                realCheckBox.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
                realCheckBox.setEnabled(!xrayBinaryPath.isEmpty());

                TextView hint = new TextView(this);
                hint.setText(
                        xrayBinaryPath.isEmpty()
                                ? "این گزینه آماده است، اما در این build هنوز فایل xray داخل APK قرار نگرفته؛ بنابراین فعلاً غیرفعال است."
                                : "اختیاری است: ابتدا TCP سریع اجرا می‌شود، سپس کانفیگ‌های برتر با xray، چند پروب واقعی، confidence و stability تست می‌شوند. این حالت کندتر است."
                );
                hint.setTextColor(muted);
                hint.setTextSize(11);
                hint.setGravity(Gravity.RIGHT);
                hint.setTextDirection(View.TEXT_DIRECTION_RTL);
                hint.setPadding(0, 0, 0, dpLocal(8));

                Button refreshButton = new Button(this);
                refreshButton.setText("به‌روزرسانی منابع از GitHub");
                refreshButton.setTextColor(text);
                refreshButton.setTextSize(13);
                refreshButton.setAllCaps(false);
                refreshButton.setGravity(Gravity.CENTER);

                TextView refreshStatus = new TextView(this);
                refreshStatus.setText("برای دریافت فوری sourceهای trusted جدید، این دکمه را بزنید. در غیر این صورت اپ هر حدود ۱ ساعت خودش بررسی می‌کند.");
                refreshStatus.setTextColor(muted);
                refreshStatus.setTextSize(11);
                refreshStatus.setGravity(Gravity.RIGHT);
                refreshStatus.setTextDirection(View.TEXT_DIRECTION_RTL);
                refreshStatus.setPadding(0, 0, 0, dpLocal(8));

                refreshButton.setOnClickListener(v -> refreshSourcesNow(refreshButton, refreshStatus));

                parent.addView(realCheckBox, index + 1);
                parent.addView(hint, index + 2);
                parent.addView(refreshButton, index + 3);
                parent.addView(refreshStatus, index + 4);
                return;
            }
        }

        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                addRealCheckOption(group.getChildAt(i));
            }
        }
    }

    private void refreshSourcesNow(Button button, TextView statusView) {
        button.setEnabled(false);
        statusView.setTextColor(muted);
        statusView.setText("در حال دریافت Remote Source Registry از GitHub...");

        new Thread(() -> {
            String message;
            boolean ok = false;
            try {
                Python py = Python.getInstance();
                PyObject raw = py.getModule("android_source_refresh").callAttr("refresh_sources_now");
                JSONObject result = new JSONObject(raw.toString());
                ok = result.optBoolean("ok", false);
                int active = result.optInt("active_sources", 0);
                String msg = result.optString("message", ok ? "منابع به‌روزرسانی شد." : "به‌روزرسانی منابع ناموفق بود.");
                message = ok
                        ? msg + " اکنون " + active + " منبع فعال آماده scan است."
                        : msg + " از cache یا registry داخلی استفاده می‌شود. منابع فعال فعلی: " + active;
            } catch (Exception exc) {
                message = "به‌روزرسانی منابع ناموفق بود: " + exc.getMessage();
            }

            boolean finalOk = ok;
            String finalMessage = message;
            runOnUiThread(() -> {
                statusView.setText(finalMessage);
                statusView.setTextColor(finalOk ? accent : muted);
                button.setEnabled(true);
            });
        }).start();
    }

    private void installStartHook(View view) {
        if (view instanceof Button) {
            Button button = (Button) view;
            CharSequence label = button.getText();
            if (label != null && label.toString().contains("شروع اسکن")) {
                button.setOnClickListener(v -> {
                    configureRealCheckBridge();
                    invokeMainStartScan();
                });
                return;
            }
        }

        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                installStartHook(group.getChildAt(i));
            }
        }
    }

    private void configureRealCheckBridge() {
        boolean enabled = realCheckBox != null && realCheckBox.isChecked() && !xrayBinaryPath.isEmpty();
        try {
            Python py = Python.getInstance();
            py.getModule("android_bridge").callAttr("set_real_check", enabled, xrayBinaryPath, 50);
        } catch (Exception ignored) {
            // The normal scan can still run without the optional real validation mode.
        }
    }

    private void invokeMainStartScan() {
        try {
            Method m = MainActivity.class.getDeclaredMethod("startScan");
            m.setAccessible(true);
            m.invoke(this);
        } catch (Exception ignored) {
            // If reflection ever fails, do nothing rather than crashing the app.
        }
    }

    private String prepareXrayBinary() {
        File nativeLib = new File(getApplicationInfo().nativeLibraryDir, "libxray.so");
        if (nativeLib.isFile()) {
            return nativeLib.getAbsolutePath();
        }
        return "";
    }

    private int dpLocal(int value) {
        float density = getResources().getDisplayMetrics().density;
        return Math.round(value * density);
    }
}
