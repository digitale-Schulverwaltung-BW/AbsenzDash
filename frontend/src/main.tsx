import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

declare global {
  interface Window {
    absenzdashConfig?: { restUrl: string; nonce: string; basename: string };
  }
}

const container = document.getElementById("absenzdash-root");
if (container) {
  const queryClient = new QueryClient();
  createRoot(container).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        {/* basename: the SPA is mounted on a WordPress page at an arbitrary path (e.g. "/absenzdash/"),
            not at the site root, so React Router needs to know that prefix to match routes.
            Deep links to /klasse/:id will additionally need a WordPress rewrite rule (or a switch to
            HashRouter) once the follow-up student-list/detail plan starts linking those routes — open
            decision for that plan, not resolved here. */}
        <BrowserRouter basename={window.absenzdashConfig?.basename}>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
