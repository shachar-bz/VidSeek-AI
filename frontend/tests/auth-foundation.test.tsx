import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { getCurrentUser, logIn, logOut, signUp } from "../src/api/auth";
import {
  request,
  subscribeToUnauthorized,
  writeToken
} from "../src/api/client";
import { AccountProvider, ProtectedRoute, PublicOnlyRoute } from "../src/auth";
import { ROUTES } from "../src/routes";

const USER = {
  id: "user-1",
  email: "person@example.com",
  display_name: "Person"
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("auth API", () => {
  it("uses the fixed endpoints and keeps request fields snake_case", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ token: "signup-token", user: USER }))
      .mockResolvedValueOnce(jsonResponse({ token: "login-token", user: USER }));
    vi.stubGlobal("fetch", fetchMock);

    await signUp({
      display_name: "Person",
      email: "person@example.com",
      password: "password123"
    });
    await logIn({ email: "person@example.com", password: "password123" });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/v1/auth/signup");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      display_name: "Person",
      email: "person@example.com",
      password: "password123"
    });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/v1/auth/login");
  });

  it("sends the stored token to me and logout", async () => {
    writeToken("stored-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(USER))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await getCurrentUser();
    await logOut();

    const meHeaders = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    const logoutHeaders = fetchMock.mock.calls[1]?.[1]?.headers as Headers;
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/v1/auth/me");
    expect(meHeaders.get("Authorization")).toBe("Bearer stored-token");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/v1/auth/logout");
    expect(logoutHeaders.get("Authorization")).toBe("Bearer stored-token");
  });

  it("reports protected 401s through the shared unauthorized channel", async () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToUnauthorized(listener);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Session expired" }, 401))
    );

    await expect(request("/v1/library")).rejects.toThrow("Session expired");
    expect(listener).toHaveBeenCalledTimes(1);

    await expect(request("/v1/auth/login", { anonymous: true })).rejects.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});

function RouteFixture({ initialPath }: { initialPath: string }) {
  return (
    <AccountProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route element={<PublicOnlyRoute />}>
            <Route path={ROUTES.signIn} element={<p>Sign-in page</p>} />
          </Route>
          <Route element={<ProtectedRoute />}>
            <Route path={ROUTES.library} element={<p>Library page</p>} />
            <Route path={ROUTES.account} element={<p>Account page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AccountProvider>
  );
}

describe("account initialization and route guards", () => {
  it("does not flash or redirect while me is pending", async () => {
    writeToken("stored-token");
    let finishRequest: ((response: Response) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((resolve) => {
          finishRequest = resolve;
        })
      )
    );

    render(<RouteFixture initialPath={ROUTES.account} />);

    expect(screen.getByText("Checking your session…")).toBeTruthy();
    expect(screen.queryByText("Sign-in page")).toBeNull();
    finishRequest?.(jsonResponse(USER));
    expect(await screen.findByText("Account page")).toBeTruthy();
  });

  it("redirects a signed-out protected route to sign in", async () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<RouteFixture initialPath={ROUTES.account} />);
    expect(await screen.findByText("Sign-in page")).toBeTruthy();
  });

  it("redirects a signed-in auth route to the library", async () => {
    writeToken("stored-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(USER)));
    render(<RouteFixture initialPath={ROUTES.signIn} />);
    expect(await screen.findByText("Library page")).toBeTruthy();
  });

  it("keeps a transient me failure in an error gate and can retry", async () => {
    writeToken("stored-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "Accounts unavailable" }, 503))
      .mockResolvedValueOnce(jsonResponse(USER));
    vi.stubGlobal("fetch", fetchMock);
    render(<RouteFixture initialPath={ROUTES.account} />);

    expect(await screen.findByText("Unable to check your session")).toBeTruthy();
    expect(screen.queryByText("Sign-in page")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Account page")).toBeTruthy();
  });

  it("clears a revoked session after me returns 401", async () => {
    writeToken("stored-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Invalid session" }, 401))
    );
    render(<RouteFixture initialPath={ROUTES.account} />);

    expect(await screen.findByText("Sign-in page")).toBeTruthy();
    expect(window.localStorage.getItem("vidseek.auth.token")).toBeNull();
  });
});
