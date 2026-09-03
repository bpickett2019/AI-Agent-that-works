import { state } from "./state.js";
import {
  getClient
} from "./ws-cdp-client.js";
const RESPONSE_TIMEOUT_MS = 15e3;
const SESSION_TTL_MS = 2e3;
const MAX_BUFFERED_EVENTS = 1e4;
const SESSION_LOST = /Session (?:with given id )?not found|Target closed|No session/i;
const BROWSER_LEVEL = (method) => method.startsWith("Target.") || method.startsWith("Browser.");
let nextMessageId = 1;
const pending = /* @__PURE__ */ new Map();
const events = [];
const eventWaiters = [];
const eventSubscribers = /* @__PURE__ */ new Set();
const pageEnabledSessions = /* @__PURE__ */ new Set();
const pendingDialogs = /* @__PURE__ */ new Map();
function isBrowserRuntime() {
  return true;
}
async function browserCdpClient() {
  return getClient();
}
function browserEgo() {
  throw new Error(
    "browserEgo() is not available in ego-browser-linux. Use browserCdpClient() instead."
  );
}
async function rawCdp(method, params = {}, sessionId = void 0, timeoutMs = RESPONSE_TIMEOUT_MS) {
  const client = await getClient();
  const response = await client.send(method, params, sessionId, timeoutMs);
  return response.result || {};
}
async function browserCdp(method, params = {}, sessionId = void 0, timeoutMs = RESPONSE_TIMEOUT_MS) {
  if (state.cdpOverride) {
    return state.cdpOverride(method, params, sessionId);
  }
  const explicit = sessionId !== void 0;
  let effective = sessionId;
  if (!explicit && !BROWSER_LEVEL(method)) {
    effective = await ensureSession();
  }
  try {
    return await rawCdp(method, params, effective, timeoutMs);
  } catch (error) {
    const lost = SESSION_LOST.test(error?.message || "");
    if (lost && !explicit && !BROWSER_LEVEL(method)) {
      invalidateSession();
      const fresh = await ensureSession();
      return rawCdp(method, params, fresh, timeoutMs);
    }
    throw error;
  }
}
async function ensureSession() {
  if (state.sessionId && Date.now() - state.sessionAt < SESSION_TTL_MS) {
    return state.sessionId;
  }
  if (state.sessionInflight) {
    return state.sessionInflight;
  }
  state.sessionInflight = (async () => {
    try {
      const client = await getClient();
      if (!client.__eventsWired) {
        client.__eventsWired = true;
        client.onClosed(() => {
          invalidateSession();
        });
        client.subscribeEvent(
          "Target.detachedFromTarget",
          void 0,
          (event) => {
            const sid = event.params?.sessionId || event.sessionId;
            if (sid) {
              pageEnabledSessions.delete(sid);
              pendingDialogs.delete(sid);
            }
            const tid = event.params?.targetId;
            if (tid && tid === state.sessionTargetId) {
              invalidateSession();
            }
          }
        );
        client.subscribeEvent(
          "Target.targetDestroyed",
          void 0,
          (event) => {
            const tid = event.params?.targetId;
            if (tid && tid === state.sessionTargetId) {
              invalidateSession();
            }
          }
        );
        client.subscribeEvent(
          "Page.javascriptDialogOpening",
          void 0,
          (event) => {
            const sid = event.sessionId || state.sessionId;
            if (sid) pendingDialogs.set(sid, event.params || {});
          }
        );
        client.subscribeEvent(
          "Page.javascriptDialogClosed",
          void 0,
          (event) => {
            const sid = event.sessionId || state.sessionId;
            if (sid) pendingDialogs.delete(sid);
          }
        );
      }
      const result = await client.send("Target.getTargets");
      const targets = (result.result?.targetInfos || []).filter(
        (t) => t.type === "page"
      );
      const preferred = state.preferredTargetId ? targets.find((t) => t.targetId === state.preferredTargetId) : null;
      const active = preferred || targets.find((t) => t.active) || targets[targets.length - 1];
      if (!active) {
        const created = await client.send("Target.createTarget", {
          url: "about:blank"
        });
        const targetId = created.result?.targetId;
        const attached = await client.send("Target.attachToTarget", {
          targetId,
          flatten: true
        });
        state.sessionId = attached.result?.sessionId || attached.sessionId;
        state.sessionTargetId = targetId;
      } else {
        const targetId = active.targetId;
        if (targetId !== state.sessionTargetId || !state.sessionId) {
          const attached = await client.send("Target.attachToTarget", {
            targetId,
            flatten: true
          });
          state.sessionId = attached.result?.sessionId || attached.sessionId;
          state.sessionTargetId = targetId;
        }
      }
      await enablePageEvents(state.sessionId);
      state.sessionAt = Date.now();
      return state.sessionId;
    } finally {
      state.sessionInflight = null;
    }
  })();
  return state.sessionInflight;
}
function invalidateSession() {
  if (state.sessionId) {
    pageEnabledSessions.delete(state.sessionId);
    pendingDialogs.delete(state.sessionId);
  }
  state.sessionId = null;
  state.sessionTargetId = null;
  state.sessionAt = 0;
  state.sessionInflight = null;
}
function setPreferredTarget(targetId) {
  state.preferredTargetId = targetId || null;
}
function clearPreferredTarget() {
  state.preferredTargetId = null;
}
function drainBrowserEvents() {
  return events.splice(0, events.length);
}
function waitForBrowserEvent(predicate, timeoutMs = state.defaultTimeout) {
  return new Promise((resolve, reject) => {
    const waiter = {
      predicate,
      resolve,
      reject,
      timer: setTimeout(() => {
        const index = eventWaiters.indexOf(waiter);
        if (index >= 0) eventWaiters.splice(index, 1);
        reject(new Error("page.waitForEvent timed out"));
      }, timeoutMs)
    };
    eventWaiters.push(waiter);
  });
}
function subscribeBrowserEvent(method, sessionId, listener) {
  const subscriber = { method, sessionId, listener };
  eventSubscribers.add(subscriber);
  return () => eventSubscribers.delete(subscriber);
}
function pendingDialog(sessionId = state.sessionId) {
  if (sessionId && pendingDialogs.has(sessionId)) {
    return { ...pendingDialogs.get(sessionId) };
  }
  return null;
}
async function enablePageEvents(sessionId) {
  if (!sessionId || pageEnabledSessions.has(sessionId)) return;
  try {
    const client = await getClient();
    await client.send("Page.enable", {}, sessionId);
    pageEnabledSessions.add(sessionId);
  } catch {
  }
}
function browserSnapshotRefsToRefMap(refMap, refs = []) {
  refMap.clear();
  for (const ref of refs) {
    if (!ref || typeof ref !== "object") continue;
    if (ref.backendNodeId === void 0 || ref.backendNodeId === null) continue;
    refMap.add(
      String(ref.backendNodeId),
      ref.backendNodeId,
      ref.role,
      ref.name,
      void 0
    );
  }
}
async function resetConnection() {
  invalidateSession();
  const { disconnectClient } = await import("./ws-cdp-client.js");
  await disconnectClient();
}
export {
  browserCdp,
  browserCdpClient,
  browserEgo,
  browserSnapshotRefsToRefMap,
  clearPreferredTarget,
  drainBrowserEvents,
  ensureSession,
  invalidateSession,
  isBrowserRuntime,
  pendingDialog,
  resetConnection,
  setPreferredTarget,
  subscribeBrowserEvent,
  waitForBrowserEvent
};
