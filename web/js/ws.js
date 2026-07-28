import { WS_BASE } from "./config.js";
import { getAccessToken } from "./api.js";

class WSClient {
  constructor() {
    this.socket = null;
    this.handlers = new Map(); // type -> Set(fn)
    this._intentionalClose = false;
    this._reconnectDelay = 1000;
  }

  connect() {
    const token = getAccessToken();
    if (!token) return;
    this._intentionalClose = false;
    this.socket = new WebSocket(`${WS_BASE}/ws?token=${encodeURIComponent(token)}`);

    this.socket.addEventListener("message", (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      const set = this.handlers.get(msg.type);
      if (set) set.forEach((fn) => fn(msg));
      const wildcard = this.handlers.get("*");
      if (wildcard) wildcard.forEach((fn) => fn(msg));
    });

    this.socket.addEventListener("close", () => {
      if (this._intentionalClose) return;
      setTimeout(() => this.connect(), this._reconnectDelay);
    });
  }

  close() {
    this._intentionalClose = true;
    this.socket?.close();
  }

  send(obj) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(obj));
    }
  }

  on(type, fn) {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type).add(fn);
    return () => this.handlers.get(type)?.delete(fn);
  }
}

export const ws = new WSClient();
