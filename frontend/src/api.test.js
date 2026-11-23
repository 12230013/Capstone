import { beforeEach, describe, expect, it, vi } from "vitest";

let api;
let fetchMock;
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });

beforeEach(async () => {
  vi.resetModules();
  vi.stubEnv("VITE_API_BASE_URL", "http://localhost:8000");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  api = await import("./api");
});

describe("authenticated API client", () => {
  it("uses the documented backend port by default in development", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    vi.stubEnv("VITE_API_PORT", "");
    vi.stubEnv("DEV", true);
    vi.resetModules();
    const localApi = await import("./api");
    fetchMock.mockResolvedValue(response({}));
    await localApi.apiFetch("/api/auth/login", { method: "POST" });
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${window.location.protocol}//${window.location.hostname}:8001/api/auth/login`);
  });

  it("keeps the browser hostname when configuring a development API port", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    vi.stubEnv("VITE_API_PORT", "8002");
    vi.stubEnv("DEV", true);
    vi.resetModules();
    const localApi = await import("./api");
    fetchMock.mockResolvedValue(response({}));
    await localApi.apiFetch("/api/auth/login", { method: "POST" });
    const url = fetchMock.mock.calls[0][0];
    expect(url.hostname).toBe(window.location.hostname);
    expect(url.port).toBe("8002");
  });

  it("times out a stalled sign-in request with a useful error", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    const result = expect(api.apiFetch("/api/auth/login", { method: "POST" }))
      .rejects.toThrow("The sign-in service took too long to respond");
    await vi.advanceTimersByTimeAsync(15000);
    await result;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("verifies the session and stores only the public profile", async () => {
    localStorage.setItem("accSessionToken", "obsolete");
    fetchMock.mockResolvedValue(response({ user: { id: "alice" }, csrf_token: "csrf" }));
    expect(await api.loadSession()).toEqual({ id: "alice" });
    expect(localStorage.getItem("accUser")).toBe('{"id":"alice"}');
    expect(localStorage.getItem("accSessionToken")).toBeNull();
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include", cache: "no-store" });
  });

  it("shares an in-flight session check between callers", async () => {
    let resolve;
    fetchMock.mockImplementation(() => new Promise(done => { resolve = done; }));
    const first = api.loadSession();
    const second = api.loadSession();
    resolve(response({ user: { id: "alice" }, csrf_token: "csrf" }));
    await Promise.all([first, second]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends cookie credentials and CSRF for a protected mutation", async () => {
    api.setCsrfToken("csrf");
    fetchMock.mockResolvedValue(response({ success: true }));
    await api.apiFetch("/api/folders", { method: "POST", body: '{"name":"Case"}' });
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8000/api/folders");
    expect(options.credentials).toBe("include");
    expect(options.headers.get("X-CSRF-Token")).toBe("csrf");
    expect(options.headers.has("Authorization")).toBe(false);
  });

  it("obtains CSRF before sending a mutation after refresh", async () => {
    fetchMock.mockResolvedValueOnce(response({ user: { id: "alice" }, csrf_token: "fresh" }))
      .mockResolvedValueOnce(response({ success: true }));
    await api.apiFetch("/api/auth/logout", { method: "POST" });
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/auth/me");
    expect(fetchMock.mock.calls[1][1].headers.get("X-CSRF-Token")).toBe("fresh");
  });

  it("does not bootstrap a session for public login", async () => {
    fetchMock.mockResolvedValue(response({ detail: "Invalid credentials" }, 401));
    const expired = vi.fn();
    window.addEventListener("acc-session-expired", expired);
    try {
      await api.apiFetch("/api/auth/login", { method: "POST", body: "{}" });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(expired).not.toHaveBeenCalled();
    } finally { window.removeEventListener("acc-session-expired", expired); }
  });

  it("clears the profile and notifies the UI when a protected call expires", async () => {
    localStorage.setItem("accUser", '{"id":"alice"}');
    fetchMock.mockResolvedValue(response({ detail: "Expired" }, 401));
    const expired = vi.fn();
    window.addEventListener("acc-session-expired", expired);
    try {
      await api.apiFetch("/api/conversations");
      expect(localStorage.getItem("accUser")).toBeNull();
      expect(expired).toHaveBeenCalledOnce();
    } finally { window.removeEventListener("acc-session-expired", expired); }
  });

  it("does not send a mutation when session verification fails", async () => {
    fetchMock.mockResolvedValue(response({ detail: "Expired" }, 401));
    await expect(api.apiFetch("/api/folders", { method: "DELETE" })).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("marks polling as background activity and preserves cancellation", async () => {
    const controller = new AbortController();
    fetchMock.mockResolvedValue(response({ activities: [] }));
    await api.apiFetch("/api/activity", { background: true, signal: controller.signal });
    const options = fetchMock.mock.calls[0][1];
    expect(options.headers.get("X-Session-Activity")).toBe("background");
    expect(options.signal).toBe(controller.signal);
    expect(options).not.toHaveProperty("background");
  });
});
