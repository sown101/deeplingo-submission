import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../app/AuthProvider";
import type { AuthGateway, AuthSessionSnapshot } from "../../lib/auth/authGateway";
import { ForgotPasswordScreen } from "./ForgotPasswordScreen";
import { ResetPasswordScreen } from "./ResetPasswordScreen";

const session: AuthSessionSnapshot = { userId: "learner-a", accessToken: "synthetic-token" };

function fakeGateway(initial: AuthSessionSnapshot | null) {
  let current = initial;
  const listeners = new Set<(value: AuthSessionSnapshot | null, event: string) => void>();
  const resetPassword = vi.fn(async (_email: string, _redirectTo: string) => {});
  const gateway: AuthGateway = {
    getClient: () => { throw new Error("unused"); },
    currentSession: vi.fn(async () => current),
    onAuthStateChange: (listener) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    signIn: vi.fn(async () => { throw new Error("unused"); }),
    signUp: vi.fn(async () => ({ needsConfirmation: true })),
    signOut: vi.fn(async () => {}),
    resetPassword,
    updatePassword: vi.fn(async () => {}),
  };
  const emit = (value: AuthSessionSnapshot | null, event: string) => {
    current = value;
    listeners.forEach((listener) => listener(value, event));
  };
  return { gateway, emit, resetPassword };
}

function mount(gateway: AuthGateway, ui: ReactElement) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AuthProvider gateway={gateway}>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("W05 password recovery presentation boundaries", () => {
  it("shows the invalid-link state for a signed-in learner WITHOUT a recovery event", async () => {
    mount(fakeGateway(session).gateway, <ResetPasswordScreen />);
    expect(await screen.findByRole("heading", { name: "Invalid link" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Set new password" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });

  it("reveals the reset form only after the PASSWORD_RECOVERY event is observed", async () => {
    const { gateway, emit } = fakeGateway(session);
    mount(gateway, <ResetPasswordScreen />);
    await screen.findByRole("heading", { name: "Invalid link" });

    act(() => emit(session, "PASSWORD_RECOVERY"));

    expect(await screen.findByRole("heading", { name: "Set new password" })).toBeVisible();
    expect(screen.getByLabelText("New password")).toBeVisible();
    expect(screen.getByLabelText("Confirm new password")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Invalid link" })).not.toBeInTheDocument();
  });

  it("shows the invalid-link state for a signed-out visitor", async () => {
    mount(fakeGateway(null).gateway, <ResetPasswordScreen />);
    expect(await screen.findByRole("heading", { name: "Invalid link" })).toBeVisible();
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });

  it("requests a reset email with neutral copy that never reveals account existence", async () => {
    const { gateway, resetPassword } = fakeGateway(null);
    mount(gateway, <ForgotPasswordScreen />);
    await userEvent.type(await screen.findByLabelText("Email"), "learner@example.invalid");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(
      "If an account exists for this email, a reset link has been sent.",
    );
    expect(resetPassword).toHaveBeenCalledWith(
      "learner@example.invalid",
      expect.stringMatching(/\/reset-password$/),
    );
  });
});
