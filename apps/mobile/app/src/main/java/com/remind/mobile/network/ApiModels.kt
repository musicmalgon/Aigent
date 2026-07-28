package com.remind.mobile.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class SignupRequest(val email: String, val password: String)

@Serializable
data class LoginRequest(val email: String, val password: String)

@Serializable
data class UserRead(
    val id: String,
    val email: String,
    @SerialName("user_type") val userType: String? = null,
)

@Serializable
data class TokenResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("token_type") val tokenType: String = "bearer",
)

object DataSource {
    const val HEALTH_PLATFORM = "health_platform"
    const val MANUAL = "manual"
    const val SYNTHETIC = "synthetic"
    const val NOT_PROVIDED = "not_provided"
}

object DataCoverage {
    const val COMPLETE = "complete"
    const val PARTIAL = "partial"
    const val UNAVAILABLE = "unavailable"
}

@Serializable
data class SourceByField(
    @SerialName("sleep_minutes") val sleepMinutes: String,
    val bedtime: String,
    @SerialName("wake_time") val wakeTime: String,
    val steps: String,
    @SerialName("active_minutes") val activeMinutes: String,
    @SerialName("exercise_minutes") val exerciseMinutes: String,
    @SerialName("work_or_study_minutes") val workOrStudyMinutes: String,
    @SerialName("rest_minutes") val restMinutes: String,
    @SerialName("schedule_count") val scheduleCount: String,
    @SerialName("subjective_fatigue") val subjectiveFatigue: String,
)

@Serializable
data class CoverageByField(
    @SerialName("sleep_minutes") val sleepMinutes: String,
    val bedtime: String,
    @SerialName("wake_time") val wakeTime: String,
    val steps: String,
    @SerialName("active_minutes") val activeMinutes: String,
    @SerialName("exercise_minutes") val exerciseMinutes: String,
    @SerialName("work_or_study_minutes") val workOrStudyMinutes: String,
    @SerialName("rest_minutes") val restMinutes: String,
    @SerialName("schedule_count") val scheduleCount: String,
    @SerialName("subjective_fatigue") val subjectiveFatigue: String,
)

@Serializable
data class DailyRecordCreate(
    val date: String,
    @SerialName("time_zone") val timeZone: String,
    @SerialName("sleep_minutes") val sleepMinutes: Int?,
    val bedtime: String?,
    @SerialName("wake_time") val wakeTime: String?,
    val steps: Int?,
    @SerialName("active_minutes") val activeMinutes: Int?,
    @SerialName("exercise_minutes") val exerciseMinutes: Int?,
    @SerialName("work_or_study_minutes") val workOrStudyMinutes: Int?,
    @SerialName("rest_minutes") val restMinutes: Int?,
    @SerialName("schedule_count") val scheduleCount: Int?,
    @SerialName("subjective_fatigue") val subjectiveFatigue: Double?,
    @SerialName("source_by_field") val sourceByField: SourceByField,
    @SerialName("coverage_by_field") val coverageByField: CoverageByField,
)

@Serializable
data class DailyRecordRead(
    @SerialName("user_id") val userId: String,
    val date: String,
    @SerialName("time_zone") val timeZone: String,
    @SerialName("sleep_minutes") val sleepMinutes: Int?,
    val bedtime: String?,
    @SerialName("wake_time") val wakeTime: String?,
    val steps: Int?,
    @SerialName("active_minutes") val activeMinutes: Int?,
    @SerialName("exercise_minutes") val exerciseMinutes: Int?,
    @SerialName("work_or_study_minutes") val workOrStudyMinutes: Int?,
    @SerialName("rest_minutes") val restMinutes: Int?,
    @SerialName("schedule_count") val scheduleCount: Int?,
    @SerialName("subjective_fatigue") val subjectiveFatigue: Double?,
    @SerialName("source_by_field") val sourceByField: SourceByField,
    @SerialName("coverage_by_field") val coverageByField: CoverageByField,
)
