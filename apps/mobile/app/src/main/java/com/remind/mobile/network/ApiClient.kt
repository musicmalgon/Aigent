package com.remind.mobile.network

import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * Dev-only client: base URL assumes `adb reverse tcp:8000 tcp:8000` is
 * forwarding the device's localhost:8000 to the backend running on the
 * host machine (see services/backend README for how to run it).
 */
object ApiClient {
    private const val BASE_URL = "http://127.0.0.1:8000/"

    private val json = Json { ignoreUnknownKeys = true }

    private val okHttpClient = OkHttpClient.Builder()
        .addInterceptor(HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BODY })
        .build()

    val service: ReMindApiService = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .client(okHttpClient)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(ReMindApiService::class.java)
}
