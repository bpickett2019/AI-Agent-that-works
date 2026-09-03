import {
  clearPreferredTarget,
  ensureSession,
  invalidateSession,
  isBrowserRuntime,
  pendingDialog,
  setPreferredTarget
} from "../browser-runtime.js";
import { getClient } from "../ws-cdp-client.js";
import { cdp, evaluate } from "../cdp-eval.js";
import { state } from "../state.js";
import { waitForDocumentLoad } from "./load.js";
const INTERNAL_URL_PREFIXES = [
  "chrome://",
  "chrome-untrusted://",
  "devtools://",
  "chrome-extension://",
  "about:"
];
async function goto(url, options = {}) {
  const navigation = await cdp("Page.navigate", { url });
  const loaded = options.waitUntil === "commit" ? false : await waitForDocumentLoad({
    timeout: options.timeout ?? 2e4,
    until: options.waitUntil === "domcontentloaded" ? "domcontentloaded" : "load"
  });
  const settle = Number(options.settle ?? 0);
  if (settle > 0) {
    await state.sleep(settle);
  }
  return { navigation, loaded };
}
async function pageInfo() {
  if (isBrowserRuntime()) {
    await ensureSession();
    const dialog = pendingDialog();
    if (dialog) {
      return { dialog };
    }
  }
  const expression = `(() => {
    const root = document.documentElement;
    return JSON.stringify({
      url: location.href,
      title: document.title,
      w: innerWidth,
      h: innerHeight,
      sx: scrollX,
      sy: scrollY,
      pw: root?.scrollWidth ?? innerWidth,
      ph: root?.scrollHeight ?? innerHeight,
    });
  })()`;
  return JSON.parse(await evaluate(expression));
}
async function listTabs(options = {}) {
  const includeChrome = options.includeChrome ?? true;
  const client = await getClient();
  const result = await client.send("Target.getTargets");
  const allTargets = result.result?.targetInfos || [];
  const tabs = allTargets.filter((t) => t.type === "page");
  return tabs.filter(
    (tab) => includeChrome || !INTERNAL_URL_PREFIXES.some(
      (prefix) => (tab.url || "").startsWith(prefix)
    )
  ).map((tab) => ({
    targetId: tab.targetId,
    title: tab.title || "",
    url: tab.url || "",
    active: Boolean(tab.active),
    index: tab.index
  }));
}
async function currentTab() {
  const tabs = await listTabs();
  const active = tabs.find((tab) => tab.active) || tabs[0];
  if (!active) {
    throw new Error("no active browser tab");
  }
  return { targetId: active.targetId, url: active.url, title: active.title };
}
async function switchTab(target) {
  const targetId = targetIdFrom(target, "switchTab");
  const tabs = await listTabs();
  currentTargetFrom(tabs, targetId, "switchTab");
  await cdp("Target.activateTarget", { targetId });
  invalidateSession();
  setPreferredTarget(targetId);
  return targetId;
}
async function newTab(url = "about:blank") {
  const client = await getClient();
  const result = await client.send("Target.createTarget", { url });
  const targetId = result.result?.targetId;
  if (!targetId) {
    throw new Error("newTab returned no targetId");
  }
  return targetId;
}
async function openOrReuseTab(url, options = {}) {
  const tabs = await listTabs({ includeChrome: false });
  const match = options.match || "exact";
  const existing = tabs.find((tab) => tabMatchesUrl(tab.url, url, match));
  if (existing) {
    await switchTab(existing.targetId);
    if (options.wait) {
      await waitForDocumentLoad({ timeout: options.timeout ?? 2e4 });
    }
    const settle2 = Number(options.settle ?? 0);
    if (settle2 > 0) {
      await state.sleep(settle2);
    }
    return { ...existing, active: true, reused: true };
  }
  const targetId = await newTab(url);
  if (options.wait !== false) {
    await waitForDocumentLoad({ timeout: options.timeout ?? 2e4 });
  }
  const settle = Number(options.settle ?? 0);
  if (settle > 0) {
    await state.sleep(settle);
  }
  return { targetId, url, title: "", active: true, reused: false };
}
async function closeTab(target = void 0) {
  const tabs = await listTabs();
  const targetId = target === void 0 ? (tabs.find((tab) => tab.active) || tabs[0])?.targetId : targetIdFrom(target, "closeTab");
  if (!targetId) throw new Error("closeTab requires a targetId");
  currentTargetFrom(tabs, targetId, "closeTab");
  await cdp("Target.closeTarget", { targetId });
  invalidateSession();
  if (state.preferredTargetId === targetId) {
    clearPreferredTarget();
  }
  if (tabs.length > 1) {
    await waitForClosedTarget(targetId);
  }
  return targetId;
}
async function ensureRealTab() {
  const tabs = await listTabs({ includeChrome: false });
  if (tabs.length === 0) {
    return null;
  }
  const current = await currentTab().catch(() => null);
  if (current?.url && !INTERNAL_URL_PREFIXES.some((prefix) => current.url.startsWith(prefix))) {
    return current;
  }
  await switchTab(tabs[0].targetId);
  return tabs[0];
}
async function iframeTarget(urlSubstring) {
  const targets = (await cdp("Target.getTargets")).targetInfos || [];
  return targets.find(
    (target) => target.type === "iframe" && (target.url || "").includes(urlSubstring)
  )?.targetId || null;
}
function tabMatchesUrl(tabUrl, wantedUrl, match) {
  if (!tabUrl) {
    return false;
  }
  if (match === "includes") {
    return tabUrl.includes(wantedUrl);
  }
  let tab;
  let wanted;
  try {
    tab = new URL(tabUrl);
    wanted = new URL(wantedUrl);
  } catch {
    return tabUrl === wantedUrl;
  }
  if (match === "origin") {
    return tab.origin === wanted.origin;
  }
  if (match === "origin+path") {
    return tab.origin === wanted.origin && trimSlash(tab.pathname) === trimSlash(wanted.pathname);
  }
  return tab.href === wanted.href;
}
function trimSlash(pathname) {
  return pathname.replace(/\/+$/, "") || "/";
}
function targetIdFrom(target, operation) {
  const targetId = typeof target === "string" ? target : target && typeof target === "object" ? target.targetId : void 0;
  if (typeof targetId !== "string" || !targetId) {
    throw new Error(
      `${operation} requires a targetId; received ${JSON.stringify(target)}`
    );
  }
  return targetId;
}
function currentTargetFrom(tabs, targetId, operation) {
  const tab = tabs.find((candidate) => candidate.targetId === targetId);
  if (tab) return tab;
  const available = tabs.map(({ targetId: targetId2, title, url }) => ({
    targetId: targetId2,
    title,
    url
  }));
  throw new Error(
    `${operation} target not found: ${JSON.stringify(targetId)}. Refresh browser.listTabs() and select a current targetId. Available tabs: ${JSON.stringify(available)}`
  );
}
async function waitForClosedTarget(targetId) {
  const deadline = state.now() + 2e3;
  while (true) {
    const tabs = await listTabs();
    if (!tabs.some((tab) => tab.targetId === targetId)) return tabs;
    if (state.now() >= deadline) {
      throw new Error(
        `closeTab timed out waiting for target to close: ${JSON.stringify(targetId)}`
      );
    }
    await state.sleep(50);
  }
}
export {
  INTERNAL_URL_PREFIXES,
  closeTab,
  currentTab,
  ensureRealTab,
  goto,
  iframeTarget,
  listTabs,
  newTab,
  openOrReuseTab,
  pageInfo,
  switchTab
};
