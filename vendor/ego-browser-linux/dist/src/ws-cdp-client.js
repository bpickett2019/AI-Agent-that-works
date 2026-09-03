import WebSocket from "ws";
const RESPONSE_TIMEOUT_MS = 15e3;
const CONNECT_TIMEOUT_MS = 1e4;
class CdpWebSocketClient {
  ws = null;
  url;
  idCounter = 1;
  pending = /* @__PURE__ */ new Map();
  eventSubscribers = /* @__PURE__ */ new Set();
  bufferedEvents = [];
  maxBufferedEvents = 1e4;
  connected = false;
  connecting = null;
  onCloseCallback = null;
  constructor(url) {
    this.url = url;
  }
  /** Discover the browser-level WebSocket endpoint from the HTTP debug server. */
  static async discoverEndpoint(host = "127.0.0.1", port = 9222) {
    const http = await import("node:http");
    return new Promise((resolve, reject) => {
      const req = http.get(
        `http://${host}:${port}/json/version`,
        (res) => {
          let data = "";
          res.on("data", (chunk) => data += chunk);
          res.on("end", () => {
            if (res.statusCode !== 200) {
              reject(new Error(`HTTP ${res.statusCode} from /json/version`));
              return;
            }
            try {
              const parsed = JSON.parse(data);
              const wsUrl = parsed.webSocketDebuggerUrl;
              if (!wsUrl) {
                reject(new Error("No webSocketDebuggerUrl in /json/version"));
                return;
              }
              const normalized = new URL(wsUrl);
              if (!normalized.port) normalized.port = String(port);
              normalized.hostname = host;
              resolve(normalized.toString());
            } catch (err) {
              reject(new Error(`Failed to parse /json/version: ${err.message}`));
            }
          });
        }
      );
      req.on("error", (err) => {
        reject(new Error(`Failed to connect to CDP at ${host}:${port}: ${err.message}`));
      });
      req.setTimeout(5e3, () => {
        req.destroy();
        reject(new Error(`Timeout connecting to CDP at ${host}:${port}`));
      });
    });
  }
  /** Connect to the browser's CDP WebSocket endpoint. */
  async connect() {
    if (this.connected && this.ws?.readyState === WebSocket.OPEN) return;
    if (this.connecting) return this.connecting;
    this.connecting = (async () => {
      const ws = new WebSocket(this.url, {
        perMessageDeflate: false,
        maxPayload: 256 * 1024 * 1024
        // 256MB — screenshots can be large
      });
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          reject(new Error(`CDP WebSocket connect timeout: ${this.url}`));
        }, CONNECT_TIMEOUT_MS);
        ws.once("open", () => {
          clearTimeout(timer);
          resolve();
        });
        ws.once("error", (err) => {
          clearTimeout(timer);
          reject(new Error(`CDP WebSocket error: ${err.message}`));
        });
      });
      this.ws = ws;
      this.connected = true;
      ws.on("message", (data) => this.handleMessage(data));
      ws.on("error", (err) => this.handleError(err));
      ws.on("close", () => this.handleClose());
    })();
    try {
      await this.connecting;
    } finally {
      this.connecting = null;
    }
  }
  /** Send a CDP command and await its response. */
  async send(method, params = {}, sessionId, timeoutMs = RESPONSE_TIMEOUT_MS) {
    if (!this.connected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      await this.connect();
    }
    const id = this.idCounter++;
    const payload = JSON.stringify({
      id,
      method,
      params,
      ...sessionId ? { sessionId } : {}
    });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP request timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (response) => {
          clearTimeout(timer);
          resolve(response);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
        timer
      });
      try {
        this.ws.send(payload);
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error);
      }
    });
  }
  /** Subscribe to CDP events matching a method (and optionally session). */
  subscribeEvent(method, sessionId, listener) {
    const subscriber = { method, sessionId, listener };
    this.eventSubscribers.add(subscriber);
    return () => this.eventSubscribers.delete(subscriber);
  }
  /** Wait for a CDP event matching a predicate. */
  waitForEvent(predicate, timeoutMs = 1e4) {
    return new Promise((resolve, reject) => {
      const waiter = {
        predicate,
        resolve,
        reject,
        timer: setTimeout(() => {
          const idx = this.eventWaiters.indexOf(waiter);
          if (idx >= 0) this.eventWaiters.splice(idx, 1);
          reject(new Error("page.waitForEvent timed out"));
        }, timeoutMs)
      };
      this.eventWaiters.push(waiter);
    });
  }
  eventWaiters = [];
  /** Drain buffered events (for legacy compatibility). */
  drainEvents() {
    return this.bufferedEvents.splice(0, this.bufferedEvents.length);
  }
  /** Reject all pending requests (for hard-stop / connection loss). */
  rejectAllPending(error) {
    const entries = [...this.pending.values()];
    this.pending.clear();
    for (const entry of entries) entry.reject(error);
  }
  /** Disconnect from the browser. */
  async disconnect() {
    this.connected = false;
    this.rejectAllPending(new Error("CDP connection closed"));
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
  isConnected() {
    return this.connected && this.ws?.readyState === WebSocket.OPEN;
  }
  onClosed(callback) {
    this.onCloseCallback = callback;
  }
  handleMessage(data) {
    let parsed;
    try {
      parsed = JSON.parse(data.toString());
    } catch {
      return;
    }
    if (parsed.id !== void 0) {
      const entry = this.pending.get(parsed.id);
      if (!entry) return;
      this.pending.delete(parsed.id);
      if (parsed.error) {
        entry.reject(
          new Error(parsed.error.message || JSON.stringify(parsed.error))
        );
      } else {
        entry.resolve(parsed);
      }
      return;
    }
    if (parsed.method) {
      let delivered = false;
      for (const subscriber of this.eventSubscribers) {
        if (subscriber.method !== parsed.method) continue;
        if (subscriber.sessionId && subscriber.sessionId !== parsed.sessionId) {
          continue;
        }
        delivered = true;
        subscriber.listener(parsed);
      }
      if (!(delivered && parsed.method === "Page.screencastFrame")) {
        this.bufferedEvents.push(parsed);
        if (this.bufferedEvents.length > this.maxBufferedEvents) {
          this.bufferedEvents.splice(
            0,
            this.bufferedEvents.length - this.maxBufferedEvents
          );
        }
      }
      for (const waiter of [...this.eventWaiters]) {
        let matched = false;
        try {
          matched = waiter.predicate(parsed);
        } catch (error) {
          clearTimeout(waiter.timer);
          this.eventWaiters.splice(this.eventWaiters.indexOf(waiter), 1);
          waiter.reject(error);
          continue;
        }
        if (!matched) continue;
        clearTimeout(waiter.timer);
        this.eventWaiters.splice(this.eventWaiters.indexOf(waiter), 1);
        waiter.resolve(parsed);
      }
    }
  }
  handleError(err) {
    this.rejectAllPending(new Error(`CDP WebSocket error: ${err.message}`));
  }
  handleClose() {
    this.connected = false;
    this.ws = null;
    this.rejectAllPending(new Error("CDP connection closed"));
    if (this.onCloseCallback) this.onCloseCallback();
  }
}
let globalClient = null;
async function getClient() {
  if (globalClient?.isConnected()) return globalClient;
  const host = process.env.EGO_BROWSER_CDP_HOST || "127.0.0.1";
  const port = parseInt(
    process.env.EGO_BROWSER_CDP_PORT || "9222",
    10
  );
  const endpoint = await CdpWebSocketClient.discoverEndpoint(host, port);
  globalClient = new CdpWebSocketClient(endpoint);
  await globalClient.connect();
  return globalClient;
}
function setClient(client) {
  globalClient = client;
}
async function disconnectClient() {
  if (globalClient) {
    await globalClient.disconnect();
    globalClient = null;
  }
}
export {
  CdpWebSocketClient,
  disconnectClient,
  getClient,
  setClient
};
