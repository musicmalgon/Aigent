package com.remind.mobile

import android.content.ActivityNotFoundException
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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
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
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.remind.mobile.network.ApiClient
import com.remind.mobile.network.LoginRequest
import com.remind.mobile.network.SignupRequest
import com.remind.mobile.ui.theme.ReMindTheme
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit

private const val TEST_ACCOUNT_EMAIL = "remind-poc-tester@example.com"
private const val TEST_ACCOUNT_PASSWORD = "PoCTester!2026"

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

    var authToken by remember { mutableStateOf<String?>(null) }
    var loginStatusText by remember { mutableStateOf("로그인 안 됨") }
    var submitResultText by remember { mutableStateOf("아직 전송하지 않음") }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        permissionGranted = granted.containsAll(HEALTH_CONNECT_PERMISSIONS)
        statusText = if (permissionGranted) "권한 승인됨" else "권한 일부 거부됨"
    }

    suspend fun refreshPermissionStatus() {
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

    LaunchedEffect(Unit) { refreshPermissionStatus() }

    // Health Connect permissions can be revoked from Health Connect's own
    // settings while this app is backgrounded (the "연동해제" case) -- a
    // value cached from first launch would silently go stale, so re-check
    // on every resume instead of trusting permissionGranted forever.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                scope.launch { refreshPermissionStatus() }
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
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

        if (!permissionGranted) {
            // Escape hatch for the "revoked, not just never-granted" case:
            // Health Connect has no OS-level "don't ask again", so
            // re-launching the request above always works too, but some
            // users expect a settings screen to fix a broken permission
            // rather than the in-app prompt.
            OutlinedButton(
                onClick = {
                    try {
                        context.startActivity(manager.manageDataIntent())
                    } catch (e: ActivityNotFoundException) {
                        statusText = "Health Connect 앱을 찾을 수 없습니다"
                    }
                }
            ) {
                Text("Health Connect 설정 열기")
            }
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

        HorizontalDivider()
        Text(text = "백엔드 연동 (2단계)")
        Text(text = loginStatusText)

        Button(
            onClick = {
                scope.launch {
                    loginStatusText = "로그인 시도 중..."
                    try {
                        try {
                            ApiClient.service.signup(
                                SignupRequest(TEST_ACCOUNT_EMAIL, TEST_ACCOUNT_PASSWORD)
                            )
                        } catch (e: HttpException) {
                            if (e.code() != 409) throw e
                        }
                        val tokenResponse = ApiClient.service.login(
                            LoginRequest(TEST_ACCOUNT_EMAIL, TEST_ACCOUNT_PASSWORD)
                        )
                        authToken = tokenResponse.accessToken
                        loginStatusText = "로그인 성공"
                    } catch (e: Exception) {
                        authToken = null
                        loginStatusText = "로그인 실패: ${e.message}"
                    }
                }
            }
        ) {
            Text("테스트 계정 로그인")
        }

        Button(
            onClick = {
                val token = authToken ?: return@Button
                scope.launch {
                    try {
                        val zoneId = ZoneId.systemDefault()
                        val targetDate = LocalDate.now(zoneId).minusDays(1)
                        val start = targetDate.atStartOfDay(zoneId).toInstant()
                        val end = targetDate.plusDays(1).atStartOfDay(zoneId).toInstant()

                        val steps = manager.readStepsTotal(start, end)
                        val sleepSessions = manager.readSleepSessions(start, end)
                        // "no data for the day" is a real, valid state the
                        // backend needs to see (it feeds the "생활데이터
                        // 부족" combined-signal case) -- so we still submit
                        // rather than blocking, but say so up front instead
                        // of silently sending an all-null record.
                        val hasAnyRealData = steps != null || sleepSessions.isNotEmpty()
                        submitResultText = if (hasAnyRealData) "전송 중..."
                            else "실제 측정값 없음 — '데이터 없음' 상태로 전송 중..."

                        val record = buildDailyRecordCreate(targetDate, zoneId, steps, sleepSessions)
                        val response = ApiClient.service.createDailyRecord(
                            "Bearer $token",
                            record,
                        )
                        submitResultText = if (hasAnyRealData) {
                            "저장 성공 (${response.date}): " +
                                "steps=${response.steps ?: "없음"}, " +
                                "sleep=${response.sleepMinutes ?: "없음"}분"
                        } else {
                            "저장 성공 (${response.date}): 데이터 없음 상태로 기록됨 (0 아님)"
                        }
                    } catch (e: HttpException) {
                        // 409 isn't really a failure from the user's
                        // point of view -- the backend enforces one
                        // record per user+date, so a repeat tap on an
                        // already-submitted day is expected, not broken.
                        submitResultText = if (e.code() == 409) {
                            "이미 어제 데이터를 전송했어요 (중복 저장 방지)"
                        } else {
                            "전송 실패: HTTP ${e.code()}"
                        }
                    } catch (e: Exception) {
                        submitResultText = "전송 실패: ${e.message}"
                    }
                }
            },
            enabled = permissionGranted && authToken != null
        ) {
            Text("어제 데이터 서버로 전송")
        }

        Text(text = submitResultText)
    }
}
