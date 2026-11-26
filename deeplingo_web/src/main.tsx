import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { ErrorBoundary } from "./app/ErrorBoundary";
import { createAppQueryClient } from "./app/queryClient";
import "@fontsource/wix-madefor-text/400.css";
import "@fontsource/wix-madefor-text/500.css";
import "@fontsource/wix-madefor-text/600.css";
import "@fontsource/wix-madefor-text/700.css";
import "./design/tokens.css";
import "./design/components.css";
import "./design/app.css";
import { applyTheme, storedTheme } from "./design/theme";

applyTheme(storedTheme());

// Only learner-independent catalog reads use this outer cache.
const queryClient = createAppQueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
