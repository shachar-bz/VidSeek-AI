import { request } from "./client";
import type { AuthResponse, AuthUser, LoginRequest, SignUpRequest } from "./types";

/** Create an account and its first website session. */
export function signUp(payload: SignUpRequest): Promise<AuthResponse> {
  return request<AuthResponse>("/v1/auth/signup", {
    method: "POST",
    body: payload,
    anonymous: true
  });
}

/** Exchange credentials for a website session. */
export function logIn(payload: LoginRequest): Promise<AuthResponse> {
  return request<AuthResponse>("/v1/auth/login", {
    method: "POST",
    body: payload,
    anonymous: true
  });
}

/** Verify the stored session and return its account. */
export function getCurrentUser(signal?: AbortSignal): Promise<AuthUser> {
  return request<AuthUser>("/v1/auth/me", { signal });
}

/** Revoke the current session. Local cleanup is owned by AccountProvider. */
export function logOut(): Promise<void> {
  return request<void>("/v1/auth/logout", { method: "POST" });
}
