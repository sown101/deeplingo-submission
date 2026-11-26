import { lazy, type ComponentType } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { RouteSuspense } from "./RouteSuspense";
import { ErrorBoundary } from "./ErrorBoundary";

describe("RouteSuspense (lazy route boundaries)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a non-blank loading state while a route chunk is pending", async () => {
    let resolveChunk: (() => void) | undefined;
    const Pending = lazy(
      () =>
        new Promise<{ default: ComponentType }>((resolve) => {
          resolveChunk = () => resolve({ default: () => <p>lazy content</p> });
        }),
    );
    render(
      <RouteSuspense>
        <Pending />
      </RouteSuspense>,
    );
    // No fabricated learner state — only a neutral loading indicator.
    expect(screen.getByText("Loading…")).toBeInTheDocument();

    resolveChunk?.();
    expect(await screen.findByText("lazy content")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).toBeNull();
  });
});

describe("failed lazy chunk recovery", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("error boundary recovers a failed chunk load into a safe reload state", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Failed = lazy(() => Promise.reject(new Error("Failed to fetch dynamically imported module")));
    render(
      <ErrorBoundary>
        <RouteSuspense>
          <Failed />
        </RouteSuspense>
      </ErrorBoundary>,
    );
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("An unexpected error occurred. Please reload the page.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    // The error is never rendered to the user.
    expect(screen.queryByText(/Failed to fetch dynamically/)).toBeNull();
  });
});
