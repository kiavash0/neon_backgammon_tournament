import { API_BASE } from "./config.js";

const ACCESS_KEY = "nbt_access_token";
const REFRESH_KEY = "nbt_refresh_token";

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY);
}

export function setTokens({ access_token, refresh_token }) {
  localStorage.setItem(ACCESS_KEY, access_token);
  if (refresh_token) localStorage.setItem(REFRESH_KEY, refresh_token);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function isLoggedIn() {
  return Boolean(getAccessToken());
}

class ApiError extends Error {
  constructor(status, body) {
    super(typeof body === "string" ? body : body?.detail || `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function request(path, { method = "GET", body, auth = true, retry = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 401 && auth && retry) {
    const refreshed = await tryRefresh();
    if (refreshed) return request(path, { method, body, auth, retry: false });
  }

  let payload = null;
  const text = await resp.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!resp.ok) throw new ApiError(resp.status, payload);
  return payload;
}

async function tryRefresh() {
  const refreshToken = localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return false;
  try {
    const tokens = await request("/auth/refresh", {
      method: "POST",
      body: { refresh_token: refreshToken },
      auth: false,
    });
    setTokens(tokens);
    return true;
  } catch {
    clearTokens();
    return false;
  }
}

export const api = {
  signup: (body) => request("/auth/signup", { method: "POST", body, auth: false }),
  login: (body) => request("/auth/login", { method: "POST", body, auth: false }),
  me: () => request("/me"),
  lobby: () => request("/lobby"),
  joinRoom: (roomId) => request(`/rooms/${roomId}/join`, { method: "POST", body: {} }),
  leaveRoom: (roomId) => request(`/rooms/${roomId}/leave`, { method: "POST", body: {} }),
  tournament: (tid) => request(`/tournaments/${tid}`),
  tournamentMatch: (tid, mid) => request(`/tournaments/${tid}/matches/${mid}`),
};

export { ApiError };
