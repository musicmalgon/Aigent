package com.remind.mobile.network

import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path

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
