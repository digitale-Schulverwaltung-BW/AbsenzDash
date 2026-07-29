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
            Known limitation (live, unresolved): deep links to /schueler and /schueler/:id have no
            matching WordPress rewrite rule, so a bookmark, browser reload, or pasted link on those
            paths 404s against WordPress directly instead of reaching the SPA. In-app navigation via
            <Link> works fine because it never triggers a real page load. Needs either a WordPress
            rewrite rule or a switch from BrowserRouter to HashRouter — see docs/deployment.md. */}
        <BrowserRouter basename={window.absenzdashConfig?.basename}>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
