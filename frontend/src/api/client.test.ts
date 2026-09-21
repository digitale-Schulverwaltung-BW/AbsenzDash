import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiDelete, apiDownload, apiGet, apiPost, apiPostFormData, apiPut } from "./client";

afterEach(() => {
  window.absenzdashConfig = undefined;
  vi.unstubAllGlobals();
});

describe("apiGet", () => {
  it("throws when absenzdashConfig is missing", async () => {
    await expect(apiGet("dashboard/nav-options")).rejects.toThrow("absenzdashConfig fehlt");
  });

  it("sends the nonce header and returns the parsed JSON body", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiGet<{ ok: boolean }>("dashboard/nav-options");

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/dashboard/nav-options",
      { headers: { "X-WP-Nonce": "abc123" } },
    );
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 403 })));

    await expect(apiGet("dashboard/stats")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiPost", () => {
  it("sends the nonce header, JSON content-type and body, returns the parsed response", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1 }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiPost<{ id: number }>("students/1/measures", { massnahmen_typ_id: 2 });

    expect(result).toEqual({ id: 1 });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/students/1/measures",
      {
        method: "POST",
        headers: { "X-WP-Nonce": "abc123", "Content-Type": "application/json" },
        body: JSON.stringify({ massnahmen_typ_id: 2 }),
      },
    );
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 422 })));

    await expect(apiPost("students/1/measures", {})).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiPut", () => {
  it("sends the nonce header, JSON content-type and body, returns the parsed response", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiPut<{ id: number }>("admin/schwellwerte/1", { schwellenwert: 5 });

    expect(result).toEqual({ id: 1 });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/admin/schwellwerte/1",
      {
        method: "PUT",
        headers: { "X-WP-Nonce": "abc123", "Content-Type": "application/json" },
        body: JSON.stringify({ schwellenwert: 5 }),
      },
    );
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 422 })));

    await expect(apiPut("admin/schwellwerte/1", {})).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiPostFormData", () => {
  it("sends the nonce header and FormData body without a Content-Type header, returns the parsed response", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const formData = new FormData();
    formData.append("schuljahr_id", "27");

    const result = await apiPostFormData<{ ok: boolean }>("admin/schuljahr-historie-import/preview", formData);

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/admin/schuljahr-historie-import/preview",
      {
        method: "POST",
        headers: { "X-WP-Nonce": "abc123" },
        body: formData,
      },
    );
    const [, options] = fetchMock.mock.calls[0];
    expect(Object.keys(options.headers)).not.toContain("Content-Type");
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 422 })));

    await expect(apiPostFormData("admin/schuljahr-historie-import/preview", new FormData())).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});

describe("apiDelete", () => {
  it("sends the nonce header and resolves without a body on success", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiDelete("students/1/exemptions/2")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/students/1/exemptions/2",
      { method: "DELETE", headers: { "X-WP-Nonce": "abc123" } },
    );
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));

    await expect(apiDelete("students/1/exemptions/2")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiDownload", () => {
  it("sends the nonce header and returns the blob with a filename parsed from Content-Disposition", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Blob(["%PDF-1.4"], { type: "application/pdf" }), {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="Muster_Max_export.pdf"', "Content-Type": "application/pdf" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiDownload("students/1/export.pdf?sections=fehlzeiten");

    expect(result.filename).toBe("Muster_Max_export.pdf");
    expect(result.blob.type).toBe("application/pdf");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/students/1/export.pdf?sections=fehlzeiten",
      { headers: { "X-WP-Nonce": "abc123" } },
    );
  });

  it("falls back to a generic filename when Content-Disposition is missing", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(new Blob(["%PDF-1.4"]), { status: 200 })),
    );

    const result = await apiDownload("students/1/export.pdf");

    expect(result.filename).toBe("export.pdf");
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));

    await expect(apiDownload("students/1/export.pdf")).rejects.toBeInstanceOf(ApiError);
  });
});
