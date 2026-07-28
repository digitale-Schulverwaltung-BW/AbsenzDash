import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

declare global {
  interface Window {
    absenzdashConfig?: { restUrl: string; nonce: string };
  }
}

const container = document.getElementById("absenzdash-root");
if (container) {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
