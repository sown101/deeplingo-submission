import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { MemoryRouter, Link, useLocation } from "react-router-dom";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";
import type { AuthGateway, AuthSessionSnapshot } from "../lib/auth/authGateway";

const session = (userId: string): AuthSessionSnapshot => ({ userId, accessToken: "synthetic-token" });
const keys = [["home", "skills"], ["library"], ["progress", "skills"], ["review"], ["practice"], ["language-profile"]];

function fakeAuth(initial: AuthSessionSnapshot | null) {
  let current = initial;
  const listeners = new Set<(value: AuthSessionSnapshot | null, event: string) => void>();
  const emit = (value: AuthSessionSnapshot | null, event = "SIGNED_IN") => {
    current = value;
    listeners.forEach((listener) => listener(value, event));
  };
  const gateway: AuthGateway = {
    getClient: () => { throw new Error("unused"); },
    currentSession: vi.fn(async () => current),
    onAuthStateChange: (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    signIn: vi.fn(async () => { throw new Error("failed login"); }),
    signUp: vi.fn(async () => ({ needsConfirmation: true })),
    signOut: vi.fn(async () => { emit(null); }),
    resetPassword: async () => {},
    updatePassword: async () => {},
  };
  return { gateway, emit };
}

function harness(auth: ReturnType<typeof fakeAuth>) {
  const publicClient = new QueryClient();
  publicClient.setQueryData(["languages"], ["public-catalog"]);
  const clients: QueryClient[] = [];
  function Probe() {
    const { status, signOut } = useAuth();
    const client = useQueryClient();
    const location = useLocation();
    const [receipt, setReceipt] = useState("empty");
    const [, rerender] = useState(0);
    clients.push(client);
    if (status !== "authenticated") return <p>Signed out</p>;
    return <div>
      <p>{location.pathname}</p>
      <p data-testid="projections">{keys.map((key) => client.getQueryData(key) ?? "empty").join("|")}</p>
      <p data-testid="receipt">{receipt}</p>
      <button onClick={() => { keys.forEach((key) => client.setQueryData(key, "A-private")); setReceipt("A-receipt"); rerender((n) => n + 1); }}>Populate A</button>
      <button onClick={() => { void signOut().catch(() => {}); }}>Logout</button>
      <Link to="/other">Change route</Link>
    </div>;
  }
  const view = render(<QueryClientProvider client={publicClient}><MemoryRouter>
    <AuthProvider gateway={auth.gateway}><Probe /></AuthProvider>
  </MemoryRouter></QueryClientProvider>);
  return { ...view, publicClient, clients, latest: () => clients[clients.length - 1] };
}

describe("W01 authenticated learner isolation", () => {
  it("preserves the same learner cache across route change and same-user restoration/refresh", async () => {
    const auth = fakeAuth(session("A"));
    const h = harness(auth);
    await userEvent.click(await screen.findByText("Populate A"));
    const clientA = h.latest();
    await userEvent.click(screen.getByText("Change route"));
    expect(screen.getByText("/other")).toBeInTheDocument();
    act(() => auth.emit(session("A")));
    await waitFor(() => expect(h.latest()).toBe(clientA));
    expect(screen.getByTestId("projections")).toHaveTextContent("A-private");
    expect(h.publicClient.getQueryData(["languages"])).toEqual(["public-catalog"]);
  });

  it("clears retired learner projections on logout while retaining public catalog", async () => {
    const auth = fakeAuth(session("A"));
    const h = harness(auth);
    await userEvent.click(await screen.findByText("Populate A"));
    const clientA = h.latest();
    await userEvent.click(screen.getByText("Logout"));
    await screen.findByText("Signed out");
    keys.forEach((key) => expect(clientA.getQueryData(key)).toBeUndefined());
    expect(h.publicClient.getQueryData(["languages"])).toEqual(["public-catalog"]);
    expect(screen.queryByText("A-receipt")).not.toBeInTheDocument();
  });

  it.each(["direct", "logout"])("isolates B from A projections and local Practice/Review receipt (%s switch)", async (mode) => {
    const auth = fakeAuth(session("A"));
    const h = harness(auth);
    await userEvent.click(await screen.findByText("Populate A"));
    const clientA = h.latest();
    if (mode === "logout") {
      await userEvent.click(screen.getByText("Logout"));
      await screen.findByText("Signed out");
    }
    act(() => auth.emit(session("B")));
    await screen.findByText("Populate A");
    await waitFor(() => expect(h.latest()).not.toBe(clientA));
    keys.forEach((key) => expect(h.latest().getQueryData(key)).toBeUndefined());
    expect(screen.getByTestId("projections")).not.toHaveTextContent("A-private");
    expect(screen.getByTestId("receipt")).toHaveTextContent("empty");
  });

  it("disposes learner data on expired session and creates a fresh scope for a later login", async () => {
    const auth = fakeAuth(session("A"));
    const h = harness(auth);
    await userEvent.click(await screen.findByText("Populate A"));
    const old = h.latest();
    act(() => auth.emit(null));
    await screen.findByText("Signed out");
    expect(old.getQueryData(["library"])).toBeUndefined();
    act(() => auth.emit(session("A")));
    await screen.findByText("Populate A");
    expect(h.latest()).not.toBe(old);
    expect(screen.getByTestId("receipt")).toHaveTextContent("empty");
  });

  it("failed login and confirmation-required signup remain unauthenticated", async () => {
    const auth = fakeAuth(null);
    harness(auth);
    await screen.findByText("Signed out");
    await expect(auth.gateway.signIn("test@invalid", "dummy")).rejects.toThrow("failed login");
    expect(await auth.gateway.signUp("test@invalid", "dummy")).toEqual({ needsConfirmation: true });
    expect(screen.queryByText("Populate A")).not.toBeInTheDocument();
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("W01 auth transition races and failures", () => {
  it("an immediate subscription snapshot wins over a stale bootstrap read", async () => {
    const auth = fakeAuth(session("A"));
    const restore = deferred<AuthSessionSnapshot | null>();
    vi.mocked(auth.gateway.currentSession).mockReturnValue(restore.promise);
    auth.gateway.onAuthStateChange = (listener) => {
      listener(session("B"), "SIGNED_IN");
      return () => {};
    };
    const h = harness(auth);
    await screen.findByText("Populate A");
    const clientB = h.latest();
    await act(async () => { restore.resolve(session("A")); await restore.promise; });
    expect(h.latest()).toBe(clientB);
  });

  it("hides UI during initial restoration and ignores a stale bootstrap after B signs in", async () => {
    const auth = fakeAuth(null);
    const restore = deferred<AuthSessionSnapshot | null>();
    vi.mocked(auth.gateway.currentSession).mockReturnValue(restore.promise);
    const h = harness(auth);
    expect(screen.getByRole("status")).toHaveTextContent("Restoring session");
    expect(screen.queryByText("Populate A")).not.toBeInTheDocument();
    act(() => auth.emit(session("B")));
    await screen.findByText("Populate A");
    const clientB = h.latest();
    await act(async () => { restore.resolve(session("A")); await restore.promise; });
    expect(h.latest()).toBe(clientB);
    expect(screen.getByTestId("receipt")).toHaveTextContent("empty");
  });

  it("fails closed on a restoration error without exposing a learner subtree", async () => {
    const auth = fakeAuth(session("A"));
    vi.mocked(auth.gateway.currentSession).mockRejectedValue(new Error("private SDK details"));
    harness(auth);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be restored");
    expect(screen.queryByText("private SDK details")).not.toBeInTheDocument();
    expect(screen.queryByText("Populate A")).not.toBeInTheDocument();
  });

  it("closes A before waiting for logout; failed logout stays quarantined and can be retried", async () => {
    const auth = fakeAuth(session("A"));
    const logout = deferred<void>();
    vi.mocked(auth.gateway.signOut).mockReturnValueOnce(logout.promise);
    const h = harness(auth);
    await userEvent.click(await screen.findByText("Populate A"));
    const clientA = h.latest();
    await userEvent.click(screen.getByText("Logout"));
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("A-receipt")).not.toBeInTheDocument();
    expect(clientA.getQueryData(["library"])).toBeUndefined();
    await act(async () => { logout.reject(new Error("remote logout failed")); });
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign out could not be confirmed");
    act(() => auth.emit(session("A")));
    expect(screen.queryByText("Populate A")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Retry sign out"));
    await screen.findByText("Signed out");
  });

  it("cancels a noncooperative old-user query and late A data cannot enter B's cache", async () => {
    const auth = fakeAuth(session("A"));
    const h = harness(auth);
    await screen.findByText("Populate A");
    const clientA = h.latest();
    const result = deferred<string>();
    const query = clientA.fetchQuery({queryKey:["library"],queryFn:() => result.promise}).catch(() => undefined);
    act(() => auth.emit(session("B")));
    await screen.findByText("Populate A");
    await waitFor(() => expect(h.latest()).not.toBe(clientA));
    await act(async () => { result.resolve("late-A"); await query; });
    expect(clientA.getQueryData(["library"])).toBeUndefined();
    expect(h.latest().getQueryData(["library"])).toBeUndefined();
    expect(screen.getByTestId("projections")).not.toHaveTextContent("late-A");
  });

  it("logout invalidates an outstanding restoration even if the gateway emits no event", async () => {
    const auth = fakeAuth(session("A"));
    const restore = deferred<AuthSessionSnapshot | null>();
    vi.mocked(auth.gateway.currentSession).mockReturnValue(restore.promise);
    // A is restored by an SDK event while the initial read remains unresolved.
    const h = harness(auth);
    act(() => auth.emit(session("A")));
    await screen.findByText("Populate A");
    vi.mocked(auth.gateway.signOut).mockResolvedValue(undefined);
    await userEvent.click(screen.getByText("Logout"));
    await screen.findByText("Signed out");
    await act(async () => { restore.resolve(session("A")); await restore.promise; });
    expect(screen.queryByText("Populate A")).not.toBeInTheDocument();
    expect(h.latest().getQueryData(["library"])).toBeUndefined();
  });
});
