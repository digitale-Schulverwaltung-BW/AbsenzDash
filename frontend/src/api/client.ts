export class ApiError extends Error {
  status: number;
  /** `detail`-Text der Backend-Fehlerantwort (z. B. bei 409/422), falls vorhanden. */
  detail: string | null;

  constructor(status: number, message: string, detail: string | null = null) {
    super(message);
    this.status = status;
    this.detail = detail;
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

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    method: "POST",
    headers: { "X-WP-Nonce": config.nonce, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, `POST ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    method: "PUT",
    headers: { "X-WP-Nonce": config.nonce, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      `PUT ${path} failed with status ${response.status}`,
      await readErrorDetail(response),
    );
  }
  return (await response.json()) as T;
}

export async function apiPostFormData<T>(path: string, formData: FormData): Promise<T> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    method: "POST",
    headers: { "X-WP-Nonce": config.nonce },
    body: formData,
  });
  if (!response.ok) {
    throw new ApiError(response.status, `POST ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiDelete(path: string): Promise<void> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    method: "DELETE",
    headers: { "X-WP-Nonce": config.nonce },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `DELETE ${path} failed with status ${response.status}`);
  }
}

function filenameFromContentDisposition(header: string | null): string {
  if (!header) {
    return "export.pdf";
  }
  const match = /filename="?([^";]+)"?/.exec(header);
  return match ? match[1] : "export.pdf";
}

export async function apiDownload(path: string): Promise<{ blob: Blob; filename: string }> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    headers: { "X-WP-Nonce": config.nonce },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed with status ${response.status}`);
  }
  const blob = await response.blob();
  const filename = filenameFromContentDisposition(response.headers.get("Content-Disposition"));
  return { blob, filename };
}
