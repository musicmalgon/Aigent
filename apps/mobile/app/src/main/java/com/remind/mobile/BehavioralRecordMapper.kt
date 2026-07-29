package com.remind.mobile

import androidx.health.connect.client.records.SleepSessionRecord
import com.remind.mobile.network.CoverageByField
import com.remind.mobile.network.DailyRecordCreate
import com.remind.mobile.network.DataCoverage
import com.remind.mobile.network.DataSource
import com.remind.mobile.network.SourceByField
import java.time.Duration
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val TIME_FORMATTER: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm:ss")

/**
 * Maps raw Health Connect reads onto the shared BehavioralDailyRecord
 * contract. Fields this PoC never queries (active/exercise/work_or_study/
 * rest minutes, schedule_count, subjective_fatigue) are marked
 * not_provided/unavailable rather than guessed -- see
 * services/ai/docs/backend_handoff_draft.md.
 */
fun buildDailyRecordCreate(
    targetDate: LocalDate,
    zoneId: ZoneId,
    steps: Long?,
    sleepSessions: List<SleepSessionRecord>,
): DailyRecordCreate {
    val mainSleepSession = sleepSessions.maxByOrNull { session ->
        Duration.between(session.startTime, session.endTime)
    }

    val sleepMinutes = mainSleepSession?.let {
        Duration.between(it.startTime, it.endTime).toMinutes().toInt()
    }
    val bedtime = mainSleepSession?.startTime
        ?.atZone(zoneId)
        ?.toLocalTime()
        ?.format(TIME_FORMATTER)
    val wakeTime = mainSleepSession?.endTime
        ?.atZone(zoneId)
        ?.toLocalTime()
        ?.format(TIME_FORMATTER)

    val sleepCoverage = if (mainSleepSession != null) DataCoverage.COMPLETE else DataCoverage.UNAVAILABLE
    val stepsCoverage = if (steps != null) DataCoverage.COMPLETE else DataCoverage.UNAVAILABLE

    return DailyRecordCreate(
        date = targetDate.toString(),
        timeZone = zoneId.id,
        sleepMinutes = sleepMinutes,
        bedtime = bedtime,
        wakeTime = wakeTime,
        steps = steps?.toInt(),
        activeMinutes = null,
        exerciseMinutes = null,
        workOrStudyMinutes = null,
        restMinutes = null,
        scheduleCount = null,
        subjectiveFatigue = null,
        sourceByField = SourceByField(
            sleepMinutes = DataSource.HEALTH_PLATFORM,
            bedtime = DataSource.HEALTH_PLATFORM,
            wakeTime = DataSource.HEALTH_PLATFORM,
            steps = DataSource.HEALTH_PLATFORM,
            activeMinutes = DataSource.NOT_PROVIDED,
            exerciseMinutes = DataSource.NOT_PROVIDED,
            workOrStudyMinutes = DataSource.NOT_PROVIDED,
            restMinutes = DataSource.NOT_PROVIDED,
            scheduleCount = DataSource.NOT_PROVIDED,
            subjectiveFatigue = DataSource.NOT_PROVIDED,
        ),
        coverageByField = CoverageByField(
            sleepMinutes = sleepCoverage,
            bedtime = sleepCoverage,
            wakeTime = sleepCoverage,
            steps = stepsCoverage,
            activeMinutes = DataCoverage.UNAVAILABLE,
            exerciseMinutes = DataCoverage.UNAVAILABLE,
            workOrStudyMinutes = DataCoverage.UNAVAILABLE,
            restMinutes = DataCoverage.UNAVAILABLE,
            scheduleCount = DataCoverage.UNAVAILABLE,
            subjectiveFatigue = DataCoverage.UNAVAILABLE,
        ),
    )
}
