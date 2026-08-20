package com.remind.mobile

import android.content.Context
import android.content.Intent
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Instant

val HEALTH_CONNECT_PERMISSIONS = setOf(
    HealthPermission.getReadPermission(StepsRecord::class),
    HealthPermission.getReadPermission(SleepSessionRecord::class),
    HealthPermission.getReadPermission(HeartRateRecord::class),
    HealthPermission.getReadPermission(ExerciseSessionRecord::class),
)

/**
 * 포그라운드 읽기 권한과 의도적으로 분리해 둔 백그라운드 읽기 권한
 * (`android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND`). 안드로이드는
 * 이 권한을 대응하는 포그라운드 권한이 이미 승인된 뒤 별도 요청으로 받도록
 * 요구하므로, HEALTH_CONNECT_PERMISSIONS에 합치면 안 된다.
 */
const val HEALTH_CONNECT_BACKGROUND_PERMISSION: String =
    HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND

class HealthConnectManager(private val context: Context) {

    private val client: HealthConnectClient? by lazy {
        if (HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE) {
            HealthConnectClient.getOrCreate(context)
        } else {
            null
        }
    }

    suspend fun hasAllPermissions(): Boolean {
        val hcClient = client ?: return false
        val granted = hcClient.permissionController.getGrantedPermissions()
        return granted.containsAll(HEALTH_CONNECT_PERMISSIONS)
    }

    /**
     * hasAllPermissions()만으로는 부족하다 -- 포그라운드 권한이 전부 승인돼도
     * 이 권한이 없으면 앱이 백그라운드일 때의 읽기는 조용히 거부된다. 주기
     * 동기화 워커는 두 검사를 모두 통과해야 실제로 데이터를 얻을 수 있다.
     */
    suspend fun hasBackgroundReadPermission(): Boolean {
        val hcClient = client ?: return false
        val granted = hcClient.permissionController.getGrantedPermissions()
        return granted.contains(HEALTH_CONNECT_BACKGROUND_PERMISSION)
    }

    /**
     * Deep-links into Health Connect so the user can review/grant access
     * outside our in-app request flow -- needed for the "revoked after
     * granting" case, where the user turns permissions off from Health
     * Connect's own settings instead of our app. Delegates to the
     * library's own intent builder rather than hardcoding an action
     * string, since it already picks the right target per OS version and
     * falls back safely if the preferred screen isn't resolvable.
     */
    fun manageDataIntent(): Intent = HealthConnectClient.getHealthConnectManageDataIntent(context)

    /**
     * Returns null when no steps reading exists for the range. Callers must
     * not treat null as 0 -- see the source/coverage contract in
     * services/ai/docs/backend_handoff_draft.md (missing != observed zero).
     */
    suspend fun readStepsTotal(start: Instant, end: Instant): Long? {
        val hcClient = client ?: return null
        val response = hcClient.aggregate(
            AggregateRequest(
                metrics = setOf(StepsRecord.COUNT_TOTAL),
                timeRangeFilter = TimeRangeFilter.between(start, end)
            )
        )
        return response[StepsRecord.COUNT_TOTAL]
    }

    suspend fun readSleepSessions(start: Instant, end: Instant): List<SleepSessionRecord> {
        val hcClient = client ?: return emptyList()
        return hcClient.readRecords(
            ReadRecordsRequest(
                SleepSessionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(start, end)
            )
        ).records
    }

    /** #146: 운동 시간(exercise_minutes) 채우는 데 씀 -- readSleepSessions와
     *  같은 패턴, 하루에 여러 번 운동했을 수 있어서 세션들을 합산은
     *  호출부(BehavioralRecordMapper)에서 한다. */
    suspend fun readExerciseSessions(start: Instant, end: Instant): List<ExerciseSessionRecord> {
        val hcClient = client ?: return emptyList()
        return hcClient.readRecords(
            ReadRecordsRequest(
                ExerciseSessionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(start, end)
            )
        ).records
    }

    suspend fun readHeartRateRecords(start: Instant, end: Instant): List<HeartRateRecord> {
        val hcClient = client ?: return emptyList()
        return hcClient.readRecords(
            ReadRecordsRequest(
                HeartRateRecord::class,
                timeRangeFilter = TimeRangeFilter.between(start, end)
            )
        ).records
    }
}
