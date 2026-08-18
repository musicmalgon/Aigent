package com.remind.mobile.network

import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * 배포된 백엔드를 가리킨다 (MainActivity의 WEB_APP_URL과 같은 호스트, 다른
 * 포트). 이 저장소엔 빌드 variant가 없어서 로컬 백엔드로 테스트하려면
 * `adb reverse tcp:8000 tcp:8000` 걸어두고 이 상수를 잠깐 "http://127.0.0.1:8000/"로
 * 바꿔 쓰면 된다 (services/backend README 참고).
 *
 * #109: 예전엔 이 상수가 거꾸로 127.0.0.1로 고정돼 있어서, Health Connect
 * 자동 동기화(SyncWorker)가 배포 환경에서는 한 번도 서버에 도달하지 못하고
 * 매번 연결 실패로 조용히 재시도만 반복하고 있었다.
 */
object ApiClient {
    private const val BASE_URL = "http://34.64.211.201:8000/"

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
