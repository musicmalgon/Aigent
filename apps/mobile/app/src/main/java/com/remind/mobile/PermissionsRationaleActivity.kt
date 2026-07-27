package com.remind.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.remind.mobile.ui.theme.ReMindTheme

/**
 * Required by the Health Connect permission system: shown when a user taps
 * "why is this data used" from the system permission grant screen, and
 * registered for the ACTION_SHOW_PERMISSIONS_RATIONALE intent (pre-Android 14)
 * plus the ViewPermissionUsageActivity alias (Android 14+).
 */
class PermissionsRationaleActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ReMindTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    Text(
                        text = "Re:Mind는 걸음 수, 수면, 심박수 데이터를 읽어와 " +
                            "생활 패턴 변화를 사용자에게 보여주는 목적으로만 사용합니다. " +
                            "데이터는 진단이 아닌 상대 비교 신호로만 활용되며, " +
                            "제3자와 공유되지 않습니다.",
                        modifier = Modifier.padding(innerPadding).padding(16.dp)
                    )
                }
            }
        }
    }
}
