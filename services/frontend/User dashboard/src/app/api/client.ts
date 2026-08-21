// API 호출 주소는 "페이지를 연 호스트"를 런타임에 그대로 따라간다.
// 예전에는 빌드 타임 상수(VITE_API_BASE_URL)로 nip.io 도메인이 박혀 있어서,
// 사용자가 IP(http://34.64.211.201:3000)로 접속해도 브라우저는 API만 굳이
// 다른 호스트(http://34.64.211.201.nip.io:8000)로 크로스 호스트 요청을 보냈다.
// 그 결과 nip.io(공용 와일드카드 DNS) 해석이 막힌 네트워크에서는 페이지는
// 멀쩡히 뜨는데 API만 전부 "Failed to fetch"로 죽었다 (#194).
// 이제 IP로 들어오면 IP로, nip.io로 들어오면 nip.io로 요청이 나간다.
const API_PORT = "8000";

export const BASE_URL: string =
  // 프론트/백엔드가 서로 다른 호스트에 뜨는 환경을 위한 명시적 탈출구.
  // 비워두면(기본) 접속한 호스트를 그대로 사용한다.
  import.meta.env.VITE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;

// 구글 OAuth 시작 주소만은 콜백과 같은 호스트로 고정해야 한다.
// SessionMiddleware가 state 쿠키를 domain 지정 없이 host-only로 굽기 때문에,
// 로그인 시작을 IP로 하면 콜백(GOOGLE_REDIRECT_URI = nip.io)에 그 쿠키가
// 실려가지 않아 state 검증이 실패한다 (#123). 그래서 여기만 빌드 타임 상수를
// 유지한다. 미설정 시(로컬 개발)에는 위의 런타임 주소로 자연스럽게 떨어진다.
export const OAUTH_BASE_URL: string = import.meta.env.VITE_OAUTH_BASE_URL || BASE_URL;

let accessToken: string | null = localStorage.getItem("access_token");

export function setAccessToken(token: string | null) {
  accessToken = token;
  if (token) {
    localStorage.setItem("access_token", token);
  } else {
    localStorage.removeItem("access_token");
  }
}

export function getAccessToken() {
  return accessToken;
}

// 상태 코드가 필요한 호출부(예: 404 = "아직 없음"과 나머지 진짜 에러를
// 구분해야 하는 경우)를 위해 status를 실어서 던진다.
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail ?? `요청 실패: ${res.status}`, res.status);
  }

  if (res.status === 204) {
    return null as T;
  }

  return res.json() as Promise<T>;
}