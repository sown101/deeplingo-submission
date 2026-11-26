import { Component, type ErrorInfo, type ReactNode } from "react";
import { T } from "../i18n/i18n";

interface ErrorBoundaryState {
  hasError: boolean;
}

// Catches unexpected render failures and maps them to a safe user-facing
// state. Raw diagnostics are never rendered; in development the error is
// logged to the console so local diagnostics remain useful.
export class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (import.meta.env.DEV) {
      console.error("Unhandled UI error", error, info.componentStack);
    }
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="page-center">
          <h1><T>Something went wrong</T></h1>
          <p><T>An unexpected error occurred. Please reload the page.</T></p>
          <button type="button" className="dl-btn dl-btn--primary" onClick={() => window.location.reload()}>
            <T>Reload</T>
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
