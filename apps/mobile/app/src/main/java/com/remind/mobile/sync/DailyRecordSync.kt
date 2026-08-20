package com.remind.mobile.sync

import com.remind.mobile.HealthConnectManager
import com.remind.mobile.buildDailyRecordCreate
import com.remind.mobile.network.ApiClient
import com.remind.mobile.network.DailyRecordCreate
import com.remind.mobile.network.DailyRecordRead
import com.remind.mobile.network.LoginRequest
import com.remind.mobile.network.SignupRequest
import retrofit2.HttpException
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

internal const val TEST_ACCOUNT_EMAIL = "remind-poc-tester@example.com"
internal const val TEST_ACCOUNT_PASSWORD = "PoCTester!2026"

/**
 * 어제치 동기화가 끝날 수 있는 상태들. 수동 전송 버튼이 이미 구분하던 상태를
 * 그대로 옮긴 것이라, 버튼과 SyncWorker가 같은 코드를 쓰면서도 각자 필요한
 * 정보(사용자 문구 / 재시도 여부)를 잃지 않는다.
 */
sealed interface SyncResult {
    data class Success(val date: String, val steps: Int?, val sleepMinutes: Int?) : SyncResult

    /** 저장은 성공했지만 그날 실제 측정값이 하나도 없었던 경우 (0이 아니라 미수집). */
    data class SuccessNoData(val date: String) : SyncResult

    /**
     * 토큰이 만료/무효화돼 401을 받은 경우. 다른 HTTP 오류와 달리 재시도로는
     * 절대 풀리지 않고(백엔드 JWT TTL 30분, refresh 토큰 없음) 저장된 토큰을
     * 지워 다시 로그인시키는 것만이 답이라, 호출부가 구분할 수 있게 별도
     * 상태로 둔다. 단, 어느 토큰을 지울지는 호출부 책임이다 -- PoC 화면은
     * 테스트 계정 토큰([signInTestAccount])을 쓰므로 실사용자 토큰을 지우면 안 된다.
     */
    data object Unauthorized : SyncResult

    data class HttpFailure(val code: Int) : SyncResult

    data class Failure(val message: String?) : SyncResult
}

/**
 * PoC 화면(HealthConnectPocScreen) 전용 테스트 계정 로그인. 토큰을 저장하지
 * 않고 호출마다 가입(이미 있으면 409 무시) 후 로그인한다 -- 원래는 #90에서
 * "영속 토큰 저장은 범위 밖"이라 남겨뒀던 PoC 단순화 그대로다.
 *
 * 실사용자 로그인은 이제 별도로 있다 ([com.remind.mobile.auth.LoginScreen] +
 * [com.remind.mobile.auth.AuthStore], #141) -- 이 함수는 개발자가 PoC
 * 화면에서 손으로 동기화를 검증할 때만 쓰고, 실제 동기화 경로(WebAppScreen의
 * "지금 동기화" 버튼, SyncWorker)는 그쪽 토큰을 쓰지 않는다.
 */
internal suspend fun signInTestAccount(): String {
    try {
        ApiClient.service.signup(SignupRequest(TEST_ACCOUNT_EMAIL, TEST_ACCOUNT_PASSWORD))
    } catch (e: HttpException) {
        if (e.code() != 409) throw e
    }
    val tokenResponse = ApiClient.service.login(
        LoginRequest(TEST_ACCOUNT_EMAIL, TEST_ACCOUNT_PASSWORD)
    )
    return tokenResponse.accessToken
}

/**
 * 어제 하루(자정~자정) 전체 Health Connect 데이터를 읽어 백엔드에 전송한다.
 * SyncWorker의 6시간 주기 자동 동기화와 PoC 화면의 "어제 데이터 서버로
 * 전송" 버튼이 이 함수를 쓴다 -- 목적이 "하루가 끝난 뒤 그 하루를 요약해
 * 보내는 것"이라 오늘 자정 이전 데이터만 다뤄야 정확하다.
 *
 * @param token 어느 계정으로 보낼지는 호출부 책임이다 (#141) -- 실사용자
 *   로그인(AuthStore에 영속 저장된 토큰)이거나, PoC 화면처럼 테스트 계정
 *   ([signInTestAccount])으로 얻은 토큰이거나 상관없이 이 함수는 그대로 쓴다.
 * @param onSubmitting POST 직전에 호출된다. 화면이 "전송 중" 문구를 실제 측정값
 *   유무에 따라 다르게 보여주는데, 그 판단이 이 함수 안에서만 가능하기 때문에
 *   콜백으로 넘긴다. 워커는 기본값(no-op)을 쓴다.
 */
suspend fun syncYesterdayRecord(
    healthConnectManager: HealthConnectManager,
    token: String,
    onSubmitting: (hasAnyRealData: Boolean) -> Unit = {},
): SyncResult {
    val zoneId = ZoneId.systemDefault()
    val targetDate = LocalDate.now(zoneId).minusDays(1)
    return syncDailyRecord(
        healthConnectManager,
        token,
        targetDate = targetDate,
        zoneId = zoneId,
        start = targetDate.atStartOfDay(zoneId).toInstant(),
        end = targetDate.plusDays(1).atStartOfDay(zoneId).toInstant(),
        onSubmitting = onSubmitting,
    )
}

/**
 * 오늘 자정부터 지금까지 Health Connect 데이터를 읽어 백엔드에 전송한다
 * (#143). WebAppScreen의 "지금 동기화" 버튼 전용 -- 웹 "오늘 기록" 화면이
 * 오늘 날짜 기록을 조회해서 채우는데, [syncYesterdayRecord]는 어제 날짜로
 * 보내서 그 화면과 안 이어졌던 문제를 고친다.
 *
 * 하루가 아직 안 끝난 채로 보내는 거라 같은 날 여러 번 누를 수 있는데, 두 번째
 * 부터는 [submitDailyRecord]가 기존 기록을 덮어쓴다 -- 누를 때마다 그 시점까지의
 * 최신 측정값으로 오늘 기록이 갱신된다.
 */
suspend fun syncTodayRecord(
    healthConnectManager: HealthConnectManager,
    token: String,
    onSubmitting: (hasAnyRealData: Boolean) -> Unit = {},
): SyncResult {
    val zoneId = ZoneId.systemDefault()
    val targetDate = LocalDate.now(zoneId)
    return syncDailyRecord(
        healthConnectManager,
        token,
        targetDate = targetDate,
        zoneId = zoneId,
        start = targetDate.atStartOfDay(zoneId).toInstant(),
        end = Instant.now(),
        onSubmitting = onSubmitting,
    )
}

private suspend fun syncDailyRecord(
    healthConnectManager: HealthConnectManager,
    token: String,
    targetDate: LocalDate,
    zoneId: ZoneId,
    start: Instant,
    end: Instant,
    onSubmitting: (hasAnyRealData: Boolean) -> Unit,
): SyncResult {
    return try {
        val steps = healthConnectManager.readStepsTotal(start, end)
        val sleepSessions = healthConnectManager.readSleepSessions(start, end)
        val exerciseSessions = healthConnectManager.readExerciseSessions(start, end)
        // "no data for the day" is a real, valid state the backend needs to
        // see (it feeds the "생활데이터 부족" combined-signal case) -- so we
        // still submit rather than blocking, but say so up front instead of
        // silently sending an all-null record.
        val hasAnyRealData = steps != null || sleepSessions.isNotEmpty() || exerciseSessions.isNotEmpty()
        onSubmitting(hasAnyRealData)

        val record = buildDailyRecordCreate(targetDate, zoneId, steps, sleepSessions, exerciseSessions)
        val response = submitDailyRecord(token, record)

        if (hasAnyRealData) {
            SyncResult.Success(response.date, response.steps, response.sleepMinutes)
        } else {
            SyncResult.SuccessNoData(response.date)
        }
    } catch (e: HttpException) {
        if (e.code() == 401) SyncResult.Unauthorized else SyncResult.HttpFailure(e.code())
    } catch (e: Exception) {
        SyncResult.Failure(e.message)
    }
}

/**
 * 하루치 기록을 만들고(POST), 그 날짜가 이미 있으면 덮어쓴다(PUT) -- 즉 upsert.
 *
 * 백엔드는 user+date에 유니크 제약이 있어서 이미 있는 날짜로 POST하면 409를
 * 준다. 예전엔 그 409를 "이미 보냈음 = 정상 종료"로 처리했는데, 그러면 웹에서
 * 먼저 만든 기록(건강 필드가 전부 null)이 하나만 있어도 그날 걸음/수면/운동이
 * 영원히 서버에 올라가지 못했다. PUT은 전체 교체 semantics라 방금 만든 payload를
 * 그대로 다시 보내면 되고, 실패하면 여기서 그대로 던져 호출부가 진짜 실패로
 * 처리하게 둔다 (409를 성공으로 삼켜서 데이터 유실을 감추지 않는다).
 */
private suspend fun submitDailyRecord(token: String, record: DailyRecordCreate): DailyRecordRead {
    return try {
        ApiClient.service.createDailyRecord("Bearer $token", record)
    } catch (e: HttpException) {
        if (e.code() != 409) throw e
        ApiClient.service.updateDailyRecord("Bearer $token", record.date, record)
    }
}
