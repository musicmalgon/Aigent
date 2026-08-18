import { apiFetch, setAccessToken } from "./client";

export interface UserRead {
  id: string;
  email: string;
  name: string;
}

export interface TokenResponse {
  access_token: string;
  token_type?: string;
}

export async function signup(email: string, password: string, name: string): Promise<UserRead> {
  return apiFetch<UserRead>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const data = await apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setAccessToken(data.access_token);
  return data;
}

export function logout() {
  setAccessToken(null);
}

// TODO: 백엔드 app/api/auth.py의 /auth/google/callback 확인 후
// 정확한 리다이렉트 주소와 쿼리 파라미터 이름으로 교체 필요.
// 지금은 "돌아올 때 ?access_token=... 쿼리로 실어준다"고 가정하고 짬.
export const GOOGLE_LOGIN_URL = "http://34.64.211.201.nip.io:8000/auth/google/login";

export function startGoogleLogin() {
  window.location.href = GOOGLE_LOGIN_URL;
}

/** 구글 로그인 콜백에서 돌아왔을 때 URL에 실려온 토큰을 잡아채는 함수.
 *  App.tsx 최상단에서 한 번 호출해주면 됨. 토큰을 찾으면 저장하고 true를 반환. */
export function consumeGoogleLoginCallback(): boolean {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("access_token");
  if (!token) return false;

  setAccessToken(token);
  // 주소창에 토큰이 남아있지 않도록 정리
  params.delete("access_token");
  const cleanUrl = window.location.pathname + (params.toString() ? `?${params.toString()}` : "");
  window.history.replaceState({}, "", cleanUrl);
  return true;
}