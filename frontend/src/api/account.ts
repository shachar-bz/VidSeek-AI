import { request } from "./client";
import type {
  AuthUser,
  ChangePasswordRequest,
  DeleteAccountRequest,
  SessionList,
  UpdateAccountRequest
} from "./types";

export function updateAccount(update: UpdateAccountRequest): Promise<AuthUser> {
  return request<AuthUser>("/v1/account", { method: "PATCH", body: update });
}

export function changePassword(update: ChangePasswordRequest): Promise<void> {
  return request<void>("/v1/account/password", { method: "POST", body: update });
}

export function deleteAccount(update: DeleteAccountRequest): Promise<void> {
  return request<void>("/v1/account", { method: "DELETE", body: update });
}

export function getSessions(signal?: AbortSignal): Promise<SessionList> {
  return request<SessionList>("/v1/auth/sessions", { signal });
}

export function revokeSession(sessionId: string): Promise<void> {
  return request<void>(`/v1/auth/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE"
  });
}

export function revokeAllSessions(): Promise<void> {
  return request<void>("/v1/auth/sessions/revoke-all", { method: "POST" });
}
