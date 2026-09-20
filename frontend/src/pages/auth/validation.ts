import { ApiError } from "../../api/client";

export interface CredentialsErrors {
  email?: string;
  password?: string;
}

export function validateCredentials(email: string, password: string): CredentialsErrors {
  const errors: CredentialsErrors = {};
  if (!email.trim()) errors.email = "Enter your email address.";
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
    errors.email = "Enter a valid email address.";
  }

  if (!password) errors.password = "Enter your password.";
  else if (password.length < 8) errors.password = "Password must be at least 8 characters.";
  else if (password.length > 72) errors.password = "Password must be 72 characters or fewer.";
  return errors;
}

export function authFailureMessage(error: unknown, operation: "sign-in" | "sign-up"): string {
  if (error instanceof ApiError) {
    if (error.status === 503) {
      return "Accounts are temporarily unavailable. Please try again shortly.";
    }
    if (operation === "sign-up" && error.status === 409) {
      return "An account already exists for this email. Sign in instead or use another email.";
    }
    if (operation === "sign-in" && error.status === 401) {
      return "The email or password is incorrect.";
    }
    // ApiError messages are normalized by api/client.ts through describeDetail, including
    // the backend's supported validation-detail array shape.
    if (error.message) return error.message;
  }
  if (error instanceof TypeError) {
    return "We couldn’t reach VidSeek. Check your connection and try again.";
  }
  return operation === "sign-in"
    ? "We couldn’t sign you in. Please try again."
    : "We couldn’t create your account. Please try again.";
}
