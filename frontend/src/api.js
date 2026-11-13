const apiBase = import.meta.env.VITE_API_BASE_URL || (
  import.meta.env.DEV ? `${window.location.protocol}//${window.location.hostname}:8000` : window.location.origin
);

let csrfToken = null;
let sessionRequest = null;

export function setCsrfToken(value) {
  csrfToken = value;
}

function sessionExpired() {
  csrfToken = null;
  localStorage.removeItem("accUser");
  localStorage.removeItem("accSessionToken");
  window.dispatchEvent(new Event("acc-session-expired"));
}

export async function loadSession() {
  if (!sessionRequest) {
    sessionRequest = (async () => {
      const response = await fetch(new URL("/api/auth/me", apiBase), {
        credentials: "include", cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.detail || "Unable to verify your session.");
        error.status = response.status;
        throw error;
      }
      csrfToken = data.csrf_token;
      localStorage.setItem("accUser", JSON.stringify(data.user));
      localStorage.removeItem("accSessionToken");
      return data.user;
    })().finally(() => { sessionRequest = null; });
  }
  return sessionRequest;
}

export async function apiFetch(path, options = {}) {
  const { background = false, ...requestOptions } = options;
  const url = new URL(path, apiBase);
  const publicEndpoint = ["/api/auth/login", "/api/auth/signup"].includes(url.pathname);
  const headers = new Headers(options.headers);
  if (background) headers.set("X-Session-Activity", "background");
  const method = (options.method || "GET").toUpperCase();
  if (!publicEndpoint && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (!csrfToken) {
      try {
        await loadSession();
      } catch (error) {
        if (error.status === 401) sessionExpired();
        throw error;
      }
    }
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(url, { ...requestOptions, headers, credentials: "include" });
  if (!publicEndpoint && response.status === 401) sessionExpired();
  return response;
}
