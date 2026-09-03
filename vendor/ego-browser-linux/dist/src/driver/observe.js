import { mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { state } from "../state.js";
import { cdp, evaluate } from "../cdp-eval.js";
import { pageInfo } from "./nav.js";
import {
  browserSnapshotRefsToRefMap,
  drainBrowserEvents,
  ensureSession,
  isBrowserRuntime,
  pendingDialog
} from "../browser-runtime.js";
import { buildEgoError } from "../ego-errors.js";
import { cdpSnapshot } from "../cdp-snapshot.js";
import { resolveElementCenter } from "../element-resolver.js";
import {
  browserRefMap,
  ensureRefMapForRef,
  registerSnapshotForRefRefresh
} from "../ref-state.js";
function drainEvents() {
  return drainBrowserEvents();
}
async function snapshotRaw(options = {}) {
  let result;
  try {
    result = await cdpSnapshot(options);
  } catch (err) {
    throw buildEgoError(err, "snapshot");
  }
  browserSnapshotRefsToRefMap(browserRefMap, result.refs || []);
  return result;
}
registerSnapshotForRefRefresh(() => snapshotRaw());
async function snapshot(options = {}) {
  const result = await snapshotRaw({
    scope: options.scope ?? "full_page",
    includeActionMarks: options.includeActionMarks ?? true,
    includeStableLocator: options.includeStableLocator ?? true
  });
  return result.content || "";
}
async function elementCenter(selectorOrRef) {
  await ensureRefMapForRef(selectorOrRef);
  return resolveElementCenter(
    { sendRaw: cdp },
    void 0,
    browserRefMap,
    selectorOrRef
  );
}
let screenshotSeq = 0;
async function screenshot(options = {}) {
  const path = options.path ?? join(tmpdir(), `ego-browser-shot-${process.pid}-${++screenshotSeq}.png`);
  const full = options.fullPage ?? false;
  const raw = options.raw ?? false;
  const params = {
    format: "png",
    captureBeyondViewport: full
  };
  if (raw) {
    if (options.clip) {
      params.clip = { ...options.clip };
    }
  } else {
    if (isBrowserRuntime()) {
      await ensureSession();
    }
    if (!pendingDialog()) {
      const dpr = Number(await evaluate("window.devicePixelRatio")) || 1;
      const cssScale = 1 / dpr;
      if (options.clip) {
        params.clip = { scale: cssScale, ...options.clip };
      } else {
        const info = await pageInfo();
        if ("dialog" in info) {
          return screenshot({ ...options, path, raw: true });
        }
        params.clip = {
          x: 0,
          y: 0,
          width: full ? info.pw : info.w,
          height: full ? info.ph : info.h,
          scale: cssScale
        };
      }
    }
  }
  const result = await cdp("Page.captureScreenshot", params);
  await mkdir(dirname(path), { recursive: true });
  await state.writeFile(path, Buffer.from(result.data, "base64"));
  return path;
}
export {
  drainEvents,
  elementCenter,
  screenshot,
  snapshot,
  snapshotRaw
};
