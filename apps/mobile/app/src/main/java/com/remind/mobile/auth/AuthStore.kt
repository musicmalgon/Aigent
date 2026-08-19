package com.remind.mobile.auth

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.io.IOException

// 앱 전체에서 하나만 있어야 하는 DataStore라 최상위 확장 프로퍼티로 둔다
// (Context마다 새로 만들면 "여러 인스턴스가 같은 파일을 가리킨다"는 경고와
// 함께 동시성 문제가 생길 수 있음 -- DataStore 공식 권장 패턴).
private val Context.authDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "auth",
)

/**
 * 실사용자 로그인 토큰을 기기에 영속 저장한다 (#141). SyncWorker처럼 UI가
 * 없는 곳에서도 같은 방식으로 읽어야 해서 Context 하나만 있으면 되게
 * 만들었다 -- Compose에도, CoroutineWorker에도 둘 다 쓴다.
 *
 * 참고: DataStore Preferences는 평문 저장소라 토큰이 암호화되지 않는다.
 * 이 프로젝트 성격(캡스톤 PoC)엔 허용 가능한 트레이드오프로 보고 넘어가지만,
 * 실제 서비스라면 EncryptedSharedPreferences/Keystore로 옮기는 걸 검토해야 한다.
 */
class AuthStore(context: Context) {
    private val dataStore = context.applicationContext.authDataStore

    private val tokenKey = stringPreferencesKey("access_token")

    val tokenFlow: Flow<String?> = dataStore.data
        .catch { e ->
            // DataStore는 읽기 중 IOException을 던질 수 있다(파일 손상 등) --
            // 로그인 여부 확인이 필요한 모든 호출부(SyncWorker 포함)가 이걸
            // 크래시로 받으면 안 되니 "로그인 안 됨"과 동일하게 처리한다.
            if (e is IOException) emit(emptyPreferences()) else throw e
        }
        .map { prefs -> prefs[tokenKey] }

    suspend fun getToken(): String? = tokenFlow.first()

    suspend fun saveToken(token: String) {
        dataStore.edit { prefs -> prefs[tokenKey] = token }
    }

    suspend fun clearToken() {
        dataStore.edit { prefs -> prefs.remove(tokenKey) }
    }
}
