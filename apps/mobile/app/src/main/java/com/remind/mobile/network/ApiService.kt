package com.remind.mobile.network

import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST

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
}
