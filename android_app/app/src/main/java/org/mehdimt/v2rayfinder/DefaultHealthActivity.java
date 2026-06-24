package org.mehdimt.v2rayfinder;

import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.chaquo.python.Python;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.reflect.Method;

/**
 * Launcher activity that keeps the MainActivity UI mostly unchanged, enables
 * TCP health checking by default, and adds an optional xray/Google-204 toggle.
 */
public class DefaultHealthActivity extends MainActivity {
    private final int text = Color.rgb(241, 246, 255);
    private final int muted = Color.rgb(160, 178, 205);
    private final int surface2 = Color.rgb(33, 47, 82);

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
                realCheckBox.setText("تست واقعی با xray / Google-204 — کندتر، دقیق‌تر");
                realCheckBox.setTextColor(text);
                realCheckBox.setTextSize(14);
                realCheckBox.setGravity(Gravity.RIGHT | Gravity.CENTER_VERTICAL);
                realCheckBox.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
                realCheckBox.setEnabled(!xrayBinaryPath.isEmpty());

                TextView hint = new TextView(this);
                hint.setText(
                        xrayBinaryPath.isEmpty()
                                ? "این گزینه آماده است، اما در این build هنوز فایل xray داخل APK قرار نگرفته؛ بنابراین فعلاً غیرفعال است."
                                : "اختیاری است: ابتدا TCP سریع اجرا می‌شود، سپس چند کانفیگ برتر با xray و Google-204 واقعاً تست می‌شوند. این حالت کندتر است."
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
            // The normal scan can still run without the optional xray mode.
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
        String[] assetNames = new String[] {
                "xray/arm64-v8a/xray",
                "xray/xray",
                "xray"
        };
        for (String assetName : assetNames) {
            try (InputStream in = getAssets().open(assetName)) {
                File dir = new File(getFilesDir(), "xray");
                if (!dir.exists() && !dir.mkdirs()) return "";
                File out = new File(dir, "xray");
                try (FileOutputStream fos = new FileOutputStream(out)) {
                    byte[] buffer = new byte[8192];
                    int read;
                    while ((read = in.read(buffer)) != -1) {
                        fos.write(buffer, 0, read);
                    }
                }
                out.setExecutable(true, false);
                return out.getAbsolutePath();
            } catch (Exception ignored) {
                // Try the next possible asset path.
            }
        }
        return "";
    }

    private int dpLocal(int value) {
        float density = getResources().getDisplayMetrics().density;
        return Math.round(value * density);
    }
}
