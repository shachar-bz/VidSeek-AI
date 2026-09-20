import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from "react";

import {
  getCurrentUser,
  logIn as requestLogin,
  logOut as requestLogout,
  signUp as requestSignUp
} from "../api/auth";
import {
  ApiError,
  readToken,
  subscribeToUnauthorized,
  writeToken
} from "../api/client";
import type { AuthUser, LoginRequest, SignUpRequest } from "../api/types";

export type AccountState =
  | { status: "loading"; user: null; initializationError: string | null }
  | { status: "authenticated"; user: AuthUser; initializationError: null }
  | { status: "unauthenticated"; user: null; initializationError: null };

export type AccountContextValue = AccountState & {
  /** Persist a session returned by the login endpoint and expose its account. */
  signIn(credentials: LoginRequest): Promise<AuthUser>;
  /** Create an account, persist its session, and expose its account. */
  signUp(details: SignUpRequest): Promise<AuthUser>;
  /** Revoke the server session when reachable, always clearing the local session. */
  signOut(): Promise<void>;
  /** Replace profile details after an authenticated account update. */
  synchronizeUser(user: AuthUser): void;
  /** Retry `/me` after a transient initialization failure. */
  retryInitialization(): void;
  /**
   * Shared escape hatch for code that receives an ApiError outside the normal request helper.
   * Returns true when the error was a 401 and the local session was cleared.
   */
  reportApiError(error: unknown): boolean;
};

const AccountContext = createContext<AccountContextValue | null>(null);

const INITIAL_STATE: AccountState = {
  status: "loading",
  user: null,
  initializationError: null
};

function initializationMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    return "Accounts are temporarily unavailable. Please try again shortly.";
  }
  return "We couldn’t verify your session. Check your connection and try again.";
}

export function AccountProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AccountState>(INITIAL_STATE);
  const [initializationAttempt, setInitializationAttempt] = useState(0);

  const clearSession = useCallback(() => {
    writeToken(null);
    setState({ status: "unauthenticated", user: null, initializationError: null });
  }, []);

  const reportApiError = useCallback(
    (error: unknown): boolean => {
      if (!(error instanceof ApiError) || !error.isUnauthorized) return false;
      clearSession();
      return true;
    },
    [clearSession]
  );

  useEffect(() => subscribeToUnauthorized(clearSession), [clearSession]);

  useEffect(() => {
    const token = readToken();
    if (!token) {
      clearSession();
      return;
    }

    const controller = new AbortController();
    setState(INITIAL_STATE);
    getCurrentUser(controller.signal)
      .then((user) => {
        if (!controller.signal.aborted) {
          setState({ status: "authenticated", user, initializationError: null });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (reportApiError(error)) return;
        setState({
          status: "loading",
          user: null,
          initializationError: initializationMessage(error)
        });
      });

    return () => controller.abort();
  }, [clearSession, initializationAttempt, reportApiError]);

  const acceptAuthentication = useCallback((token: string, user: AuthUser): AuthUser => {
    writeToken(token);
    setState({ status: "authenticated", user, initializationError: null });
    return user;
  }, []);

  const signIn = useCallback(
    async (credentials: LoginRequest) => {
      const response = await requestLogin(credentials);
      return acceptAuthentication(response.token, response.user);
    },
    [acceptAuthentication]
  );

  const signUp = useCallback(
    async (details: SignUpRequest) => {
      const response = await requestSignUp(details);
      return acceptAuthentication(response.token, response.user);
    },
    [acceptAuthentication]
  );

  const signOut = useCallback(async () => {
    try {
      if (readToken()) await requestLogout();
    } catch {
      // A revoked session or unavailable API must never strand a local signed-in state.
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const synchronizeUser = useCallback((user: AuthUser) => {
    setState({ status: "authenticated", user, initializationError: null });
  }, []);

  const retryInitialization = useCallback(() => {
    setInitializationAttempt((attempt) => attempt + 1);
  }, []);

  const value = useMemo<AccountContextValue>(
    () => ({
      ...state,
      signIn,
      signUp,
      signOut,
      synchronizeUser,
      retryInitialization,
      reportApiError
    }),
    [reportApiError, retryInitialization, signIn, signOut, signUp, state, synchronizeUser]
  );

  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

export function useAccount(): AccountContextValue {
  const account = useContext(AccountContext);
  if (!account) throw new Error("useAccount must be used inside AccountProvider");
  return account;
}
