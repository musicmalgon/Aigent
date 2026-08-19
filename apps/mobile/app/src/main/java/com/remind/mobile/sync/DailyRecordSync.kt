package com.remind.mobile.sync

import com.remind.mobile.HealthConnectManager
import com.remind.mobile.buildDailyRecordCreate
import com.remind.mobile.network.ApiClient
import com.remind.mobile.network.LoginRequest
import com.remind.mobile.network.SignupRequest
import retrofit2.HttpException
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

    /** 백엔드가 user+date 중복을 막아 409를 준 경우 -- 실패가 아니라 정상 종료. */
    data object AlreadySubmitted : SyncResult

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
 * 어제 하루치 Health Connect 데이터를 읽어 백엔드에 전송한다. 수동 전송 버튼과
 * 주기 실행 워커가 공유하는 단일 경로이므로 Compose에 의존하지 않는다.
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
    return try {
        val zoneId = ZoneId.systemDefault()
        val targetDate = LocalDate.now(zoneId).minusDays(1)
        val start = targetDate.atStartOfDay(zoneId).toInstant()
        val end = targetDate.plusDays(1).atStartOfDay(zoneId).toInstant()

        val steps = healthConnectManager.readStepsTotal(start, end)
        val sleepSessions = healthConnectManager.readSleepSessions(start, end)
        // "no data for the day" is a real, valid state the backend needs to
        // see (it feeds the "생활데이터 부족" combined-signal case) -- so we
        // still submit rather than blocking, but say so up front instead of
        // silently sending an all-null record.
        val hasAnyRealData = steps != null || sleepSessions.isNotEmpty()
        onSubmitting(hasAnyRealData)

        val record = buildDailyRecordCreate(targetDate, zoneId, steps, sleepSessions)
        val response = ApiClient.service.createDailyRecord("Bearer $token", record)

        if (hasAnyRealData) {
            SyncResult.Success(response.date, response.steps, response.sleepMinutes)
        } else {
            SyncResult.SuccessNoData(response.date)
        }
    } catch (e: HttpException) {
        // 409 isn't really a failure from the user's point of view -- the
        // backend enforces one record per user+date, so a repeat submission
        // of an already-sent day is expected, not broken.
        if (e.code() == 409) SyncResult.AlreadySubmitted else SyncResult.HttpFailure(e.code())
    } catch (e: Exception) {
        SyncResult.Failure(e.message)
    }
}
