export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getConfig(): { restUrl: string; nonce: string } {
  if (typeof window === "undefined" || !window.absenzdashConfig) {
    throw new Error(
      "absenzdashConfig fehlt - die SPA muss ueber den [absenzdash]-Shortcode eingebunden sein",
    );
  }
  return window.absenzdashConfig;
}

export async function apiGet<T>(path: string): Promise<T> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    headers: { "X-WP-Nonce": config.nonce },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}
