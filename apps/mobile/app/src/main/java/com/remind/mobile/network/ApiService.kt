package com.remind.mobile.network

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

interface ReMindApiService {
    @POST("/auth/signup")
    suspend fun signup(@Body request: SignupRequest): UserRead

    @POST("/auth/login")
    suspend fun login(@Body request: LoginRequest): TokenResponse

    @POST("/api/v1/behavioral-records")
    suspend fun createDailyRecord(
        @Header("Authorization") authorization: String,
        @Body record: DailyRecordCreate,
    ): DailyRecordRead

    // 전체 교체(full replace)라 POST와 같은 DailyRecordCreate를 그대로 보낸다.
    // 백엔드가 body의 date와 URL의 date가 다르면 422를 주므로 둘을 반드시 맞춰야 한다
    // (services/backend/app/api/behavioral_records.py의 update_behavioral_record).
    @PUT("/api/v1/behavioral-records/{recordDate}")
    suspend fun updateDailyRecord(
        @Header("Authorization") authorization: String,
        @Path("recordDate") recordDate: String,
        @Body record: DailyRecordCreate,
    ): DailyRecordRead

    @GET("/api/v1/behavioral-records")
    suspend fun listBehavioralRecords(
        @Header("Authorization") authorization: String,
        @Query("date_from") dateFrom: String,
        @Query("date_to") dateTo: String,
    ): List<DailyRecordRead>

    // 204 No Content 응답이므로 body 역직렬화를 시도하지 않는 Response<Unit>로 감싼다.
    @DELETE("/api/v1/behavioral-records/{recordDate}")
    suspend fun deleteBehavioralRecord(
        @Header("Authorization") authorization: String,
        @Path("recordDate") recordDate: String,
    ): Response<Unit>

    @GET("/api/v1/consents")
    suspend fun getConsents(
        @Header("Authorization") authorization: String,
    ): List<ConsentRecordRead>

    @POST("/api/v1/consents")
    suspend fun grantConsent(
        @Header("Authorization") authorization: String,
        @Body request: ConsentGrantRequest,
    ): ConsentRecordRead

    @DELETE("/api/v1/consents/{consentType}")
    suspend fun withdrawConsent(
        @Header("Authorization") authorization: String,
        @Path("consentType") consentType: String,
    ): ConsentRecordRead
}
