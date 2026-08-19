export const BASE_URL = import.meta.env.VITE_API_BASE_URL;

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