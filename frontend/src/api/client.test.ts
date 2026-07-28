import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet } from "./client";

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
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 403 })));

    await expect(apiGet("dashboard/stats")).rejects.toBeInstanceOf(ApiError);
  });
});
