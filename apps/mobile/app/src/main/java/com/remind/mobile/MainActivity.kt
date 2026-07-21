package com.remind.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import com.remind.mobile.ui.theme.ReMindTheme
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.temporal.ChronoUnit

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ReMindTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    HealthConnectPocScreen(modifier = Modifier.padding(innerPadding))
                }
            }
        }
    }
}

@Composable
fun HealthConnectPocScreen(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val manager = remember { HealthConnectManager(context) }
    val scope = rememberCoroutineScope()

    var statusText by remember { mutableStateOf("Health Connect 상태 확인 중...") }
    var permissionGranted by remember { mutableStateOf(false) }
    var resultText by remember { mutableStateOf("아직 조회하지 않음") }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        permissionGranted = granted.containsAll(HEALTH_CONNECT_PERMISSIONS)
        statusText = if (permissionGranted) "권한 승인됨" else "권한 일부 거부됨"
    }

    LaunchedEffect(Unit) {
        statusText = when (HealthConnectClient.getSdkStatus(context)) {
            HealthConnectClient.SDK_AVAILABLE -> {
                permissionGranted = manager.hasAllPermissions()
                if (permissionGranted) "Health Connect 사용 가능 · 권한 승인됨"
                else "Health Connect 사용 가능 · 권한 필요"
            }
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED ->
                "Health Connect 앱 업데이트가 필요합니다"
            else -> "이 기기에서는 Health Connect를 사용할 수 없습니다"
        }
    }

    Column(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(text = statusText)

        Button(
            onClick = { permissionLauncher.launch(HEALTH_CONNECT_PERMISSIONS) },
            enabled = !permissionGranted
        ) {
            Text("권한 요청")
        }

        Button(
            onClick = {
                scope.launch {
                    val end = Instant.now()
                    val start = end.minus(7, ChronoUnit.DAYS)

                    val steps = manager.readStepsTotal(start, end)
                    val sleepSessions = manager.readSleepSessions(start, end)
                    val heartRateRecords = manager.readHeartRateRecords(start, end)

                    resultText = buildString {
                        append("최근 7일 걸음 수: ")
                        append(steps?.toString() ?: "데이터 없음 (0이 아니라 미수집)")
                        append("\n수면 세션: ${sleepSessions.size}건")
                        append("\n심박수 기록: ${heartRateRecords.size}건")
                    }
                }
            },
            enabled = permissionGranted
        ) {
            Text("최근 7일 데이터 조회")
        }

        Text(text = resultText)
    }
}
