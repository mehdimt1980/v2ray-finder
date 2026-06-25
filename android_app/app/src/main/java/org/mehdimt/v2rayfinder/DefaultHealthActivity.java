package org.mehdimt.v2rayfinder;

import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.TextView;

import com.chaquo.python.Python;

import java.io.File;
import java.lang.reflect.Method;

/**
 * Launcher activity that keeps the MainActivity UI mostly unchanged, enables
 * TCP health checking by default, and adds the optional Real Validation v2 toggle.
 */
public class DefaultHealthActivity extends MainActivity {
    private final int text = Color.rgb(241, 246, 255);
    private final int muted = Color.rgb(160, 178, 205);

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

                parent.addView(realCheckBox, index + 1);
                parent.addView(hint, index + 2);
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
