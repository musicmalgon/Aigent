package com.remind.mobile.sync

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.remind.mobile.HealthConnectManager
import com.remind.mobile.auth.AuthStore
import java.util.concurrent.TimeUnit

const val DAILY_SYNC_WORK_NAME = "health_connect_daily_sync"

/**
 * 앱을 열지 않아도 어제치 데이터가 서버로 올라가게 하는 주기 작업.
 *
 * DI 프레임워크가 없는 코드베이스라 의존성은 doWork() 안에서 직접 만든다.
 */
class SyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val manager = HealthConnectManager(applicationContext)

        // 권한 미승인은 일시적 오류가 아니다 -- 재시도해도 사용자가 승인하기
        // 전까지는 결과가 같으므로 이번 실행만 조용히 건너뛴다. 백그라운드
        // 권한까지 봐야 하는 이유: 포그라운드 권한만 있으면 이 시점의 읽기가
        // 예외 없이 빈 결과로 돌아와 "데이터 없음" 기록을 잘못 올릴 수 있다.
        if (!manager.hasAllPermissions() || !manager.hasBackgroundReadPermission()) {
            return Result.success()
        }

        // 로그인 전(#141)이면 보낼 계정이 없다 -- 권한 미승인과 같은 이유로
        // 일시적 오류가 아니라 "사용자가 로그인하기 전까지는 결과가 같은"
        // 상태라 조용히 건너뛴다.
        val authStore = AuthStore(applicationContext)
        val token = authStore.getToken() ?: return Result.success()

        return when (val result = syncYesterdayRecord(manager, token)) {
            is SyncResult.Success,
            is SyncResult.SuccessNoData -> Result.success()

            // 토큰 만료(백엔드 JWT TTL 30분)는 재시도로 못 푼다. 여기서 지우지
            // 않으면 앱은 계속 "로그인됨"으로 보이면서 동기화만 조용히 실패하므로,
            // 지워서 다음 앱 실행 때 로그인 화면이 다시 뜨게 한다. 지우는 순간
            // AuthStore.tokenFlow가 흘러 화면 쪽(MainActivity)도 같이 따라온다.
            SyncResult.Unauthorized -> {
                authStore.clearToken()
                Result.failure()
            }

            // 5xx는 서버 쪽 일시 장애일 수 있으니 WorkManager의 백오프에 재시도를
            // 맡긴다. 그 외 4xx(유효성 등)는 같은 입력으로 재시도해도 같은 응답이다.
            is SyncResult.HttpFailure ->
                if (result.code >= 500) Result.retry() else Result.failure()

            // HTTP 응답 자체를 못 받은 경우(네트워크 단절 등)는 전형적인 일시 오류.
            is SyncResult.Failure -> Result.retry()
        }
    }
}

/**
 * 앱 시작 시 무조건 등록한다. 권한이 아직 없어도 워커 자신이 no-op으로 끝내므로
 * 권한 상태를 스케줄링 조건으로 삼지 않는다.
 *
 * 6시간 주기는 데모용이다. 실제 운영이라면 "어제 하루 요약"을 보내는 작업이니
 * 하루 1회로 충분하지만, 그러면 시연 중에 한 번도 실행되지 않는다. (WorkManager의
 * 최소 주기는 15분이나 이 작업의 데이터 신선도 요구에는 과하다.)
 * KEEP: 앱을 다시 켜도 기존 스케줄을 리셋하거나 중복 등록하지 않는다.
 */
fun scheduleDailySync(context: Context) {
    val request = PeriodicWorkRequestBuilder<SyncWorker>(6, TimeUnit.HOURS)
        .setConstraints(
            Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
        )
        .build()

    WorkManager.getInstance(context).enqueueUniquePeriodicWork(
        DAILY_SYNC_WORK_NAME,
        ExistingPeriodicWorkPolicy.KEEP,
        request,
    )
}
