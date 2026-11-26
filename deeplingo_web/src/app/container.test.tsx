import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { ContainerProvider, useContainer, type AppContainer } from "./container";
import type { AuthGateway } from "../lib/auth/authGateway";

const gateway: AuthGateway = {
  getClient: () => { throw new Error("unused"); },
  currentSession: vi.fn(async () => null),
  onAuthStateChange: () => () => {},
  signIn: vi.fn(async () => { throw new Error("unused"); }),
  signUp: vi.fn(async () => ({ needsConfirmation: true })),
  signOut: vi.fn(async () => {}),
  resetPassword: async () => {},
  updatePassword: async () => {},
};

function Probe() {
  const container = useContainer();
  return <p>{container === provided ? "provided" : container.gateway === gateway ? "built" : "other"}</p>;
}

const provided = { gateway: "provided-gateway" } as unknown as AppContainer;

describe("useContainer", () => {
  it("calls its hooks in the same order with and without a provided container", async () => {
    const queryClient = new QueryClient();
    const view = (container: AppContainer | null) => (
      <QueryClientProvider client={queryClient}>
        <AuthProvider gateway={gateway}><ContainerProvider container={container as AppContainer}><Probe /></ContainerProvider></AuthProvider>
      </QueryClientProvider>
    );
    const { rerender } = render(view(null));
    expect(await screen.findByText("built")).toBeInTheDocument();
    rerender(view(provided)); // fewer hooks than the render before would throw here
    expect(await screen.findByText("provided")).toBeInTheDocument();
    rerender(view(null));
    expect(await screen.findByText("built")).toBeInTheDocument();
  });

  it("still needs either a container or the auth provider", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<ContainerProvider container={null as unknown as AppContainer}><Probe /></ContainerProvider>))
      .toThrow("useAuth must be used within AuthProvider");
    quiet.mockRestore();
  });
});
