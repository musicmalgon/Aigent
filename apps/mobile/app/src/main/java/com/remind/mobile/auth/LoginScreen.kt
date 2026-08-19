package com.remind.mobile.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.remind.mobile.network.ApiClient
import com.remind.mobile.network.LoginRequest
import kotlinx.coroutines.launch
import retrofit2.HttpException

/**
 * 실사용자 로그인 화면 (#141). 이미 배포돼 동작 중인 백엔드 /auth/login을
 * 그대로 재사용한다 -- 회원가입은 웹(Auth.tsx)에서 이미 하고 있으므로 여기선
 * 로그인만 다룬다. 성공하면 토큰을 그대로 위(MainActivity)로 올려보내고,
 * 영속 저장은 호출부 책임으로 남긴다 (이 화면은 DataStore를 몰라도 됨).
 */
@Composable
fun LoginScreen(modifier: Modifier = Modifier, onLoginSuccess: (String) -> Unit) {
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun submit() {
        if (email.isBlank() || password.isBlank()) {
            errorText = "이메일과 비밀번호를 모두 입력해 주세요."
            return
        }
        errorText = null
        loading = true
        scope.launch {
            try {
                val response = ApiClient.service.login(LoginRequest(email.trim(), password))
                onLoginSuccess(response.accessToken)
            } catch (e: HttpException) {
                // 백엔드는 이메일/비밀번호 불일치를 401로만 구분해서 준다
                // (services/backend/app/api/auth.py) -- 그 외 상태코드는
                // 일시적/서버 쪽 문제로 보고 원문을 그대로 보여준다.
                errorText = if (e.code() == 401) {
                    "이메일 또는 비밀번호가 올바르지 않습니다."
                } else {
                    "로그인 중 오류가 발생했습니다 (HTTP ${e.code()})"
                }
            } catch (e: Exception) {
                errorText = "로그인 중 오류가 발생했습니다: ${e.message}"
            } finally {
                loading = false
            }
        }
    }

    Column(
        modifier = modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(text = "Re:Mind 로그인")
        Text(text = "건강 데이터 자동 동기화를 쓰려면 웹과 같은 계정으로 로그인해 주세요.")

        OutlinedTextField(
            value = email,
            onValueChange = { email = it },
            label = { Text("이메일") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
        )
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            label = { Text("비밀번호") },
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )

        errorText?.let { Text(text = it) }

        Button(
            onClick = { submit() },
            enabled = !loading,
            modifier = Modifier.padding(top = 16.dp),
        ) {
            if (loading) {
                CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp))
            }
            Text(if (loading) "로그인 중..." else "로그인")
        }
    }
}
