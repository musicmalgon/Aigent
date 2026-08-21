package com.remind.mobile

import android.content.ActivityNotFoundException
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.remind.mobile.auth.AuthStore
import com.remind.mobile.auth.LoginScreen
import com.remind.mobile.network.ApiClient
import com.remind.mobile.network.ConsentGrantRequest
import com.remind.mobile.network.ConsentType
import com.remind.mobile.sync.SyncResult
import com.remind.mobile.sync.scheduleDailySync
import com.remind.mobile.sync.signInTestAccount
import com.remind.mobile.sync.syncTodayRecord
import com.remind.mobile.sync.syncYesterdayRecord
import com.remind.mobile.ui.theme.ReMindTheme
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.time.Instant
import java.time.LocalDate
import java.time.temporal.ChronoUnit

// 배포된 웹 프론트엔드 주소. network_security_config.xml의 cleartext 허용 IP와
// 반드시 같이 맞춰야 한다 (#102).
private const val WEB_APP_URL = "http://34.64.211.201:3000"

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        scheduleDailySync(applicationContext)
        enableEdgeToEdge()
        setContent {
            ReMindTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    val authStore = remember { AuthStore(applicationContext) }
                    val scope = rememberCoroutineScope()

                    // 저장된 토큰을 한 번 읽어올 때까지는 로그인/웹앱 어느 쪽도
                    // 섣불리 그리지 않는다 -- null을 "로그인 안 됨"으로 오해해서
                    // 로그인 화면이 잠깐 깜빡였다 사라지는 걸 막기 위함
                    // (App.tsx의 restoringSession과 같은 이유, #119).
                    var authToken by remember { mutableStateOf<String?>(null) }
                    var authLoaded by remember { mutableStateOf(false) }
                    // 한 번 읽고 마는 게 아니라 계속 구독한다. 토큰이 지워지는
                    // 순간(401 만료 / 웹 로그아웃)은 이 화면 밖의 코루틴에서
                    // 오는데, 예전처럼 최초 1회만 읽으면 그 변화가 화면에
                    // 도달하지 못해 앱이 영원히 "로그인됨"으로 보였다.
                    LaunchedEffect(Unit) {
                        authStore.tokenFlow.collect { token ->
                            authToken = token
                            authLoaded = true
                        }
                    }

                    // 웹 프론트엔드가 대시보드/기록/리포트 등 실사용자 화면을 이미
                    // 다 갖고 있으므로 웹앱을 기본 화면으로 띄운다. PoC 화면은
                    // Health Connect 권한/동기화를 손으로 검증할 때만 쓰는
                    // 보조 화면이라 웹 화면에서 링크로만 들어간다 (#102).
                    var showPocScreen by remember { mutableStateOf(false) }

                    when {
                        !authLoaded -> {
                            // 아주 짧은 순간이라 별도 로딩 화면 없이 빈 화면으로 둠.
                        }
                        authToken == null -> {
                            // 실사용자 로그인 게이트 (#141) -- 이 토큰은 WebView의
                            // 웹 로그인(localStorage)과는 별개다. Health Connect
                            // 동기화가 어느 계정으로 갈지 네이티브 쪽이 알아야 해서
                            // 여기서 한 번 더 받는다. SSO 연동은 범위 밖으로 남김.
                            LoginScreen(
                                modifier = Modifier.padding(innerPadding),
                                onLoginSuccess = { token ->
                                    // 저장만 하면 위의 tokenFlow 구독이
                                    // authToken을 갱신한다 (화면 전환의 단일 경로).
                                    scope.launch { authStore.saveToken(token) }
                                },
                            )
                        }
                        showPocScreen -> {
                            HealthConnectPocScreen(
                                modifier = Modifier.padding(innerPadding),
                                onBackToWebApp = { showPocScreen = false },
                            )
                        }
                        else -> {
                            WebAppScreen(
                                modifier = Modifier.padding(innerPadding),
                                onOpenPocScreen = { showPocScreen = true },
                                authToken = authToken!!,
                                onSessionEnded = { scope.launch { authStore.clearToken() } },
                            )
                        }
                    }
                }
            }
        }
    }
}

// 배포된 웹 프론트엔드를 그대로 띄우는 화면(앱의 기본 화면). 네이티브 토큰을
// 주입하지 않고 웹 자체 로그인(Auth.tsx)에 맡긴다 -- SSO 연동은 후속 과제로
// 남김 (#102).
//
// AndroidView는 Compose 트리 안에 기존 View 시스템 컴포넌트(WebView 등)를
// 끼워 넣을 때 쓰는 브릿지다. factory는 View를 한 번만 생성하고, update는
// 리컴포지션마다(그리고 생성 직후) 호출돼 최신 상태를 반영한다.
//
// @param onSessionEnded 네이티브 세션을 끝내야 할 때(토큰 만료 401 / 웹에서
//   로그아웃) 호출한다. 호출부가 AuthStore를 지우면 tokenFlow를 타고
//   로그인 화면이 다시 뜬다 -- 두 경우 모두 결과가 같으므로 경로를 하나만 둔다.
@Composable
fun WebAppScreen(
    modifier: Modifier = Modifier,
    onOpenPocScreen: () -> Unit,
    authToken: String,
    onSessionEnded: () -> Unit,
) {
    var webView by remember { mutableStateOf<WebView?>(null) }
    var canGoBack by remember { mutableStateOf(false) }

    // WebView는 factory에서 한 번만 만들어지므로 그때 붙잡은 콜백이 오래 남는다.
    // rememberUpdatedState로 감싸 최신 콜백을 보게 한다.
    val currentOnSessionEnded by rememberUpdatedState(onSessionEnded)

    // "지금 동기화" 버튼 (#141) -- 숨겨진 PoC 화면이 아니라 앱의 기본 화면에
    // 노출해서, 6시간 주기 SyncWorker를 기다리지 않고 바로 오늘/어제 데이터를
    // 보낼 수 있게 한다.
    val context = LocalContext.current
    val healthConnectManager = remember { HealthConnectManager(context) }
    val scope = rememberCoroutineScope()
    var syncing by remember { mutableStateOf(false) }
    var syncStatusText by remember { mutableStateOf<String?>(null) }

    // 예전엔 권한이 없으면 "PoC 테스트 화면에서 먼저 허용해 주세요"라는
    // 안내만 보여줬다 -- 그 권한 요청 UI(특히 백그라운드 동기화 권한)가
    // 실제로는 숨겨진 개발자 화면 안에만 있어서, 거길 스스로 찾아 들어가지
    // 않는 일반 사용자는 배경 자동 동기화를 영원히 켤 방법이 없었다(#H9).
    // 여기서 PoC 화면과 같은 2단계 요청(포그라운드 -> 승인되면 이어서
    // 백그라운드)을 기본 화면에서 직접 하도록 한다.
    var permissionGranted by remember { mutableStateOf(false) }
    var pendingSyncAfterPermission by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        permissionGranted = healthConnectManager.hasAllPermissions()
    }

    suspend fun performSync() {
        syncing = true
        syncStatusText = "동기화 중..."
        // 오늘 기록 화면(웹)이 오늘 날짜로 조회하므로, 어제가 아니라 오늘
        // 자정~지금 범위로 보내야 그 화면에 이어진다 (#143).
        val result = syncTodayRecord(healthConnectManager, authToken)
        syncStatusText = when (result) {
            is SyncResult.Success -> "동기화 완료 (${result.date}) — 오늘 기록 화면에서 확인해 보세요"
            is SyncResult.SuccessNoData -> "동기화 완료 — 오늘은 아직 기록된 측정값이 없었어요"
            // 만료된 토큰을 그대로 두면 이 버튼은 앞으로도 계속
            // 401만 낸다. 지워서 로그인 화면으로 돌려보낸다
            // (이 문구는 화면이 곧 교체되며 사라진다).
            SyncResult.Unauthorized -> {
                currentOnSessionEnded()
                "로그인이 만료됐어요 — 다시 로그인해 주세요"
            }
            is SyncResult.HttpFailure -> "동기화 실패 (HTTP ${result.code})"
            is SyncResult.Failure -> "동기화 실패: ${result.message}"
        }
        syncing = false
    }

    // 백그라운드 권한은 포그라운드 권한이 먼저 승인된 뒤에만 별개 요청으로
    // 받을 수 있다(안드로이드 제약, PoC 화면과 동일 이유) -- 그래서 launcher를
    // 둘로 분리하고, 포그라운드 승인 콜백에서 이어서 호출한다. 자동 동기화를
    // 켜는 게 목적이라 이 단계 결과와 무관하게 방금 요청한 동기화는 진행한다.
    val backgroundPermissionLauncher = rememberLauncherForActivityResult(
        contract = PermissionController.createRequestPermissionResultContract()
    ) { /* 상태는 SyncWorker가 실행마다 다시 확인하므로 여기서 따로 안 들고 있음 */ }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        permissionGranted = granted.containsAll(HEALTH_CONNECT_PERMISSIONS)
        if (permissionGranted) {
            backgroundPermissionLauncher.launch(setOf(HEALTH_CONNECT_BACKGROUND_PERMISSION))
        }
        if (pendingSyncAfterPermission) {
            pendingSyncAfterPermission = false
            if (permissionGranted) {
                scope.launch { performSync() }
            } else {
                syncStatusText = "Health Connect 권한을 승인해야 동기화할 수 있어요."
            }
        }
    }

    // 여기가 앱의 홈 화면이라, 웹뷰 안에 뒤로 갈 탐색 기록이 있을 때만
    // 시스템 뒤로가기를 가로챈다. 기록이 없으면 가로채지 않고 시스템 기본
    // 동작(앱 종료/백그라운드 전환)에 맡긴다 -- canGoBack()은 자동으로
    // 리컴포지션을 트리거하는 값이 아니라서, WebViewClient 콜백에서 페이지
    // 이동이 생길 때마다 상태로 동기화해둬야 BackHandler의 enabled가
    // 정확해진다.
    BackHandler(enabled = canGoBack) {
        webView?.goBack()
    }

    Column(modifier = modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            TextButton(
                onClick = {
                    if (syncing) return@TextButton
                    if (!permissionGranted) {
                        // 예전엔 여기서 PoC 화면으로 안내만 하고 끝났다 -- 이제
                        // 이 화면에서 바로 실제 권한 요청을 띄우고, 승인되면
                        // 이어서 동기화까지 진행한다(#H9).
                        pendingSyncAfterPermission = true
                        permissionLauncher.launch(HEALTH_CONNECT_PERMISSIONS)
                        return@TextButton
                    }
                    scope.launch { performSync() }
                },
            ) {
                Text(if (syncing) "동기화 중..." else "지금 동기화")
            }

            // Health Connect 권한/동기화 수동 검증용 개발자 진입점.
            // 일반 사용자 플로우엔 없어도 되지만, 검증 화면 자체를
            // 없애지는 않기로 했다 (#102 범위).
            TextButton(onClick = onOpenPocScreen) {
                Text("PoC 테스트 화면")
            }
        }
        syncStatusText?.let { Text(text = it, modifier = Modifier.padding(horizontal = 8.dp)) }

        AndroidView(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            factory = { context ->
                WebView(context).apply {
                    // React 앱이 localStorage에 로그인 토큰을 저장하는 방식이라
                    // DOM storage가 없으면 로그인 상태가 유지되지 않는다.
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    addJavascriptInterface(
                        WebAuthBridge { currentOnSessionEnded() },
                        WEB_AUTH_BRIDGE_NAME,
                    )
                    webViewClient = object : WebViewClient() {
                        // WebViewClient를 지정하지 않으면 링크 클릭 시 외부
                        // 브라우저로 빠져나간다 -- 이 오버라이드가 그걸 막는
                        // 동시에 뒤로가기 가능 여부도 갱신해준다.
                        override fun doUpdateVisitedHistory(
                            view: WebView,
                            url: String?,
                            isReload: Boolean,
                        ) {
                            canGoBack = view.canGoBack()
                        }

                        override fun onPageFinished(view: WebView, url: String?) {
                            // 우리 웹앱 문서에서만 감시자를 심는다. 페이지 스크립트가
                            // 다 돈 뒤라 React가 이미 마운트돼 있고, 로그아웃은
                            // 그 뒤 사용자 조작으로 일어나므로 놓치지 않는다.
                            if (url != null && url.startsWith(WEB_APP_URL)) {
                                view.evaluateJavascript(WEB_AUTH_WATCHER_JS, null)
                            }
                        }
                    }
                    loadUrl(WEB_APP_URL)
                }
            },
            update = { webView = it },
        )
    }
}

private const val WEB_AUTH_BRIDGE_NAME = "ReMindNative"

/** 웹앱(client.ts)이 로그인 토큰을 담아두는 localStorage 키. */
private const val WEB_ACCESS_TOKEN_KEY = "access_token"

/**
 * 웹뷰 안에서 로그아웃이 일어났다는 걸 네이티브에 알려주는 브릿지 (#C8).
 *
 * 웹 로그아웃은 자기 localStorage만 지우고 끝나서 네이티브는 그 사실을 알 방법이
 * 없었다. 그 결과 웹에서 다른 계정으로 갈아타도 네이티브는 예전 계정 토큰으로
 * 건강 데이터를 계속 올렸다. URL로는 감지할 수 없다 -- 웹앱이 화면 전환을
 * React 상태로만 하는 SPA라 로그아웃해도 주소가 그대로다.
 *
 * 주의 1: 이 메서드는 UI 스레드가 아니라 WebView의 JS 브릿지 스레드에서
 * 불린다. 호출부는 스레드 안전해야 한다(여기 콜백은 코루틴 launch만 한다).
 * 주의 2: addJavascriptInterface로 노출한 객체는 이 웹뷰가 여는 모든 페이지가
 * 부를 수 있다. 여기서 할 수 있는 일이 "이 기기의 네이티브 토큰을 지운다"뿐이라
 * 피해가 강제 로그아웃에 그쳐 PoC 범위에서는 감수한다 (origin 제한이 필요하면
 * androidx.webkit의 WebMessageListener로 옮겨야 하는데 의존성이 늘어난다).
 */
private class WebAuthBridge(private val onWebLoggedOut: () -> Unit) {
    @JavascriptInterface
    fun onLogout() {
        onWebLoggedOut()
    }
}

/**
 * 웹앱의 로그인 토큰이 지워지는 순간을 잡아 [WebAuthBridge]로 알린다.
 *
 * localStorage 인스턴스에 직접 메서드를 덮어쓸 수는 없다 -- Storage에는 이름
 * 있는 프로퍼티 setter가 있어서 `localStorage.removeItem = fn`이 함수를 씌우는
 * 대신 "removeItem"이라는 키에 값을 저장해버린다. 그래서 prototype 쪽을 고친다.
 */
private const val WEB_AUTH_WATCHER_JS = """
(function () {
  if (window.__remindAuthWatcherInstalled) return;
  var proto = window.Storage && window.Storage.prototype;
  if (!proto) return;
  window.__remindAuthWatcherInstalled = true;

  var removeItem = proto.removeItem;
  proto.removeItem = function (key) {
    removeItem.apply(this, arguments);
    if (this === window.localStorage && key === '$WEB_ACCESS_TOKEN_KEY') {
      $WEB_AUTH_BRIDGE_NAME.onLogout();
    }
  };

  var clear = proto.clear;
  proto.clear = function () {
    clear.apply(this, arguments);
    if (this === window.localStorage) {
      $WEB_AUTH_BRIDGE_NAME.onLogout();
    }
  };
})();
"""

@Composable
fun HealthConnectPocScreen(modifier: Modifier = Modifier, onBackToWebApp: () -> Unit = {}) {
    val context = LocalContext.current
    val manager = remember { HealthConnectManager(context) }
    val scope = rememberCoroutineScope()

    // 웹앱이 기본 화면이므로, 여기서 뒤로가기를 누르면 항상 웹 화면으로
    // 돌아간다 (여기 자체를 벗어나 앱을 종료하는 경로는 없음).
    BackHandler { onBackToWebApp() }

    var statusText by remember { mutableStateOf("Health Connect 상태 확인 중...") }
    var permissionGranted by remember { mutableStateOf(false) }
    var backgroundPermissionGranted by remember { mutableStateOf(false) }
    var resultText by remember { mutableStateOf("아직 조회하지 않음") }

    var authToken by remember { mutableStateOf<String?>(null) }
    var loginStatusText by remember { mutableStateOf("로그인 안 됨") }
    var submitResultText by remember { mutableStateOf("아직 전송하지 않음") }

    var healthDataConsentGranted by remember { mutableStateOf(false) }
    var consentStatusText by remember { mutableStateOf("동의 상태 확인 전") }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        permissionGranted = granted.containsAll(HEALTH_CONNECT_PERMISSIONS)
        statusText = if (permissionGranted) "권한 승인됨" else "권한 일부 거부됨"
    }

    // 백그라운드 읽기 권한은 별도 런처로 분리한다. 안드로이드는 이 권한을
    // 포그라운드 권한이 이미 승인된 뒤 별개 요청으로 받도록 요구해서, 위
    // 요청에 합쳐 보내면 거부될 수 있다.
    val backgroundPermissionLauncher = rememberLauncherForActivityResult(
        contract = PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        backgroundPermissionGranted = granted.contains(HEALTH_CONNECT_BACKGROUND_PERMISSION)
    }

    suspend fun refreshPermissionStatus() {
        statusText = when (HealthConnectClient.getSdkStatus(context)) {
            HealthConnectClient.SDK_AVAILABLE -> {
                permissionGranted = manager.hasAllPermissions()
                backgroundPermissionGranted = manager.hasBackgroundReadPermission()
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

    // Grant only once both preconditions hold. The GET-then-POST pair lives in
    // one coroutine on purpose: splitting "check existing consent" and "grant
    // if missing" across the login handler and a separate effect would let both
    // fire a grant call for the same user.
    LaunchedEffect(permissionGranted, authToken) {
        val token = authToken ?: return@LaunchedEffect
        if (!permissionGranted) return@LaunchedEffect
        try {
            val consents = ApiClient.service.getConsents("Bearer $token")
            val current = consents.find { it.consentType == ConsentType.HEALTH_DATA }
            if (current?.status == "granted") {
                healthDataConsentGranted = true
                consentStatusText = "건강 데이터 동의 상태: 등록됨"
            } else {
                val granted = ApiClient.service.grantConsent(
                    "Bearer $token",
                    ConsentGrantRequest(ConsentType.HEALTH_DATA, "health_connect_permission_screen"),
                )
                healthDataConsentGranted = true
                consentStatusText = "건강 데이터 동의 등록됨 (${granted.grantedAt})"
            }
        } catch (e: Exception) {
            consentStatusText = "동의 상태 확인 실패: ${e.message}"
        }
    }

    Column(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // PoC 화면은 검증용 보조 화면이라, 웹 화면으로 돌아가는 진입점만
        // 얹는다 (#102). 나머지 화면(대시보드/기록/리포트 등)은 이미 웹에 있음.
        Button(onClick = onBackToWebApp) {
            Text("웹 앱으로 돌아가기")
        }
        HorizontalDivider()

        Text(text = statusText)

        Button(
            onClick = { permissionLauncher.launch(HEALTH_CONNECT_PERMISSIONS) },
            enabled = !permissionGranted
        ) {
            Text("권한 요청")
        }

        // 2단계 요청: 포그라운드 권한이 승인된 뒤에만 노출한다.
        if (permissionGranted && !backgroundPermissionGranted) {
            Button(
                onClick = {
                    backgroundPermissionLauncher.launch(setOf(HEALTH_CONNECT_BACKGROUND_PERMISSION))
                }
            ) {
                Text("백그라운드 동기화 권한 요청")
            }
        }

        Text(
            text = if (backgroundPermissionGranted) {
                "백그라운드 동기화 권한: 승인됨 (앱을 열지 않아도 자동 전송)"
            } else {
                "백그라운드 동기화 권한: 없음 (앱을 열었을 때만 전송)"
            }
        )

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
                    val exerciseSessions = manager.readExerciseSessions(start, end)

                    resultText = buildString {
                        append("최근 7일 걸음 수: ")
                        append(steps?.toString() ?: "데이터 없음 (0이 아니라 미수집)")
                        append("\n수면 세션: ${sleepSessions.size}건")
                        append("\n심박수 기록: ${heartRateRecords.size}건")
                        append("\n운동 세션: ${exerciseSessions.size}건")
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
                        authToken = signInTestAccount()
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
                    // 백그라운드 워커와 완전히 같은 경로를 탄다. 여기서는
                    // 결과를 화면 문구로 옮기는 일만 한다. 이 화면은 테스트
                    // 계정 토큰(signInTestAccount)을 쓴다 -- 실사용자 계정으로
                    // 보내려면 웹앱 화면의 "지금 동기화" 버튼을 쓴다 (#141).
                    val result = syncYesterdayRecord(manager, token) { hasAnyRealData ->
                        submitResultText = if (hasAnyRealData) "전송 중..."
                            else "실제 측정값 없음 — '데이터 없음' 상태로 전송 중..."
                    }
                    submitResultText = when (result) {
                        is SyncResult.Success ->
                            "저장 성공 (${result.date}): " +
                                "steps=${result.steps ?: "없음"}, " +
                                "sleep=${result.sleepMinutes ?: "없음"}분"
                        is SyncResult.SuccessNoData ->
                            "저장 성공 (${result.date}): 데이터 없음 상태로 기록됨 (0 아님)"
                        // 여기 토큰은 테스트 계정(signInTestAccount) 것이라
                        // 실사용자 토큰(AuthStore)을 건드리면 안 된다 -- 위
                        // "테스트 계정 로그인"을 다시 누르면 된다.
                        SyncResult.Unauthorized ->
                            "테스트 계정 토큰이 만료됐어요 — 다시 로그인해 주세요"
                        is SyncResult.HttpFailure -> "전송 실패: HTTP ${result.code}"
                        is SyncResult.Failure -> "전송 실패: ${result.message}"
                    }
                }
            },
            enabled = permissionGranted && authToken != null
        ) {
            Text("어제 데이터 서버로 전송")
        }

        Text(text = submitResultText)

        HorizontalDivider()
        Text(text = "동의 관리 (4단계)")
        Text(text = consentStatusText)

        Button(
            onClick = {
                val token = authToken ?: return@Button
                scope.launch {
                    try {
                        val withdrawn = ApiClient.service.withdrawConsent(
                            "Bearer $token",
                            ConsentType.HEALTH_DATA,
                        )
                        healthDataConsentGranted = false

                        // 이미 전송된 기록 정리(best-effort). 목록 API가 range 쿼리를 28일로
                        // 제한하므로 그보다 오래된 기록은 남는다 -- 수명이 짧은 PoC 데모
                        // 데이터 기준으로 허용 가능한 트레이드오프이며 전체 계정 purge는 아니다.
                        val today = LocalDate.now()
                        val syncedRecords = ApiClient.service.listBehavioralRecords(
                            "Bearer $token",
                            dateFrom = today.minusDays(27).toString(),
                            dateTo = today.toString(),
                        )
                        var deletedCount = 0
                        for (record in syncedRecords) {
                            try {
                                val response = ApiClient.service.deleteBehavioralRecord(
                                    "Bearer $token",
                                    record.date,
                                )
                                if (response.isSuccessful) deletedCount++
                            } catch (e: Exception) {
                                // best-effort: 한 날짜의 삭제 실패가 나머지를 중단시키지 않는다.
                            }
                        }

                        consentStatusText =
                            "건강 데이터 동의 철회됨 (${withdrawn.withdrawnAt}), 기존 기록 ${deletedCount}건 삭제"
                    } catch (e: HttpException) {
                        consentStatusText = if (e.code() == 404) {
                            "철회할 동의가 없습니다"
                        } else {
                            "동의 철회 실패: HTTP ${e.code()}"
                        }
                    } catch (e: Exception) {
                        consentStatusText = "동의 철회 실패: ${e.message}"
                    }
                }
            },
            enabled = healthDataConsentGranted && authToken != null
        ) {
            Text("건강 데이터 연동 동의 철회")
        }
    }
}
