export const API_BASE = window.location.hostname
  ? `${window.location.protocol}//${window.location.hostname}:8000`
  : "http://127.0.0.1:8000";

export const WS_BASE = API_BASE.replace(/^http/, "ws");
