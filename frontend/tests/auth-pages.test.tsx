import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { App } from "../src/App";
import { AccountProvider } from "../src/auth";
import { AuthShowcaseCarousel } from "../src/pages/auth/AuthShowcaseCarousel";
import { PasswordField } from "../src/pages/auth/PasswordField";

beforeEach(() => {
  window.localStorage.clear();
});

describe("auth showcase", () => {
  it("offers five local examples and keeps the faux videos non-interactive", () => {
    render(<AuthShowcaseCarousel />);

    expect(screen.getAllByRole("button", { name: /Show example \d of 5/ })).toHaveLength(5);
    expect(screen.getByText("What does the video say about evaporation?")).toBeTruthy();
    expect(
      screen.getByRole("img", { name: "A lecturer explaining the water cycle to a classroom" })
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /play/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Next example" }));
    expect(screen.getByText("When does the chef add the fresh basil?")).toBeTruthy();
    expect(screen.getByRole("img", { name: "A chef demonstrating a fresh pasta recipe" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Show example 5 of 5" }));
    expect(screen.getByText("Which materials reduce the building's footprint?")).toBeTruthy();
  });
});

describe("auth page controls", () => {
  it("can reveal and hide a password without changing its value", () => {
    render(
      <PasswordField
        value="correct horse"
        onChange={vi.fn()}
        autoComplete="current-password"
      />
    );

    const input = screen.getByLabelText(/Password/) as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(input.type).toBe("text");
    expect(input.value).toBe("correct horse");
    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(input.type).toBe("password");
  });

  it("renders the real sign-up page at the public route", async () => {
    render(
      <AccountProvider>
        <MemoryRouter initialEntries={["/sign-up"]}>
          <App />
        </MemoryRouter>
      </AccountProvider>
    );

    expect(await screen.findByRole("heading", { name: "Find any moment." })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign up" }).getAttribute("aria-current")).toBe(
      "page"
    );
    expect(screen.getByRole("button", { name: "Create account" })).toBeTruthy();
  });
});
