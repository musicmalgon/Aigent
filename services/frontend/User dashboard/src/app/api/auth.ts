import { apiFetch, setAccessToken } from "./client";

export interface UserRead {
  id: string;
  email: string;
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