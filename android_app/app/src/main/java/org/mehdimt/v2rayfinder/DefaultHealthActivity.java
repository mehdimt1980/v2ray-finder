package org.mehdimt.v2rayfinder;

import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.CheckBox;

/**
 * Launcher activity that keeps the MainActivity UI unchanged but enables
 * TCP health checking by default for non-technical users.
 */
public class DefaultHealthActivity extends MainActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        enableHealthCheckByDefault(getWindow().getDecorView());
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
}
