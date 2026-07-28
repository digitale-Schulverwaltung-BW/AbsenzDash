import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

declare global {
  interface Window {
    absenzdashConfig?: { restUrl: string; nonce: string };
  }
}

const container = document.getElementById("absenzdash-root");
if (container) {
  const queryClient = new QueryClient();
  createRoot(container).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
