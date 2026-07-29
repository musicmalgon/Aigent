package com.remind.mobile

import android.content.Context
import android.content.Intent
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
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
)

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
