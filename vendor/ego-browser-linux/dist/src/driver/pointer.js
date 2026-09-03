import { cdp, evaluate } from "../cdp-eval.js";
import { browserCdp } from "../browser-runtime.js";
import { elementCenter } from "./observe.js";
import { resolveAndCall } from "./element-ops.js";
import { waitForSelector } from "./waits.js";
const INPUT_EVENT_DELAY_MS = 25;
const INPUT_DISPATCH_TIMEOUT_MS = 1e3;
let currentMousePoint = { x: 0, y: 0, sessionId: void 0 };
async function click(target, options = {}) {
  const point = await resolveMouseTarget(target, options.timeout);
  rememberMousePoint(point);
  const button = options.button || "left";
  const buttons = pressedButtons(button);
  const clickCount = options.clickCount ?? 1;
  maybeHighlight(point, options.label);
  const probeId = await installClickProbe(point);
  let dispatchError = null;
  try {
    await dispatchMouse(point, "mouseMoved", {
      button: "none",
      buttons: 0
    });
    await inputEventDelay();
    await dispatchMouse(point, "mousePressed", {
      button,
      buttons,
      clickCount
    });
    await inputEventDelay();
    await dispatchMouse(point, "mouseReleased", {
      button,
      buttons: 0,
      clickCount
    });
  } catch (error) {
    if (!isInputDispatchTimeout(error)) throw error;
    dispatchError = error;
  }
  const completed = await finishClickProbe(point, probeId, clickCount);
  if (dispatchError && !completed) throw dispatchError;
}
async function dblclick(target, options = {}) {
  await click(target, { ...options, clickCount: 2 });
}
async function hover(target, options = {}) {
  const point = await resolveMouseTarget(target, options.timeout);
  rememberMousePoint(point);
  maybeHighlight(point, options.label);
  const probeId = await installHoverProbe(point);
  let dispatchError = null;
  try {
    await dispatchMouse(point, "mouseMoved", { buttons: 0 });
  } catch (error) {
    if (!isInputDispatchTimeout(error)) throw error;
    dispatchError = error;
  }
  const completed = await finishHoverProbe(point, probeId);
  if (dispatchError && !completed) throw dispatchError;
}
async function drag(points, options = {}) {
  if (!Array.isArray(points) || points.length < 2) {
    throw new Error("drag requires at least two points");
  }
  const resolved = [];
  for (const point of points) {
    resolved.push(await resolveMouseTarget(point, options.timeout));
  }
  const button = options.button || "left";
  const buttons = pressedButtons(button);
  const first = resolved[0];
  const last = resolved.at(-1);
  if (last) {
    rememberMousePoint(last);
  }
  maybeHighlight(first, options.label);
  const probeId = await installMouseUpProbe(last);
  let dispatchError = null;
  try {
    await dispatchMouse(first, "mousePressed", {
      button,
      buttons,
      clickCount: 1
    });
    await inputEventDelay();
    for (let i = 1; i < resolved.length; i += 1) {
      const point = resolved[i];
      await dispatchMouse(
        { ...point, sessionId: point.sessionId ?? first.sessionId },
        "mouseMoved",
        {
          button,
          buttons
        }
      );
      await inputEventDelay(options.delay > 0 ? options.delay : void 0);
    }
    await dispatchMouse(
      { ...last, sessionId: last.sessionId ?? first.sessionId },
      "mouseReleased",
      {
        button,
        buttons: 0,
        clickCount: 1
      }
    );
  } catch (error) {
    if (!isInputDispatchTimeout(error)) throw error;
    dispatchError = error;
  }
  const completed = await finishDragProbe(resolved, probeId, button);
  if (dispatchError && !completed) throw dispatchError;
}
async function down(options = {}) {
  const button = options.button || "left";
  await dispatchMouse(currentMousePoint, "mousePressed", {
    button,
    buttons: pressedButtons(button),
    clickCount: options.clickCount ?? 1
  });
}
async function up(options = {}) {
  const button = options.button || "left";
  await dispatchMouse(currentMousePoint, "mouseReleased", {
    button,
    buttons: 0,
    clickCount: options.clickCount ?? 1
  });
}
function inputEventDelay(ms = INPUT_EVENT_DELAY_MS) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
async function installClickProbe(point) {
  if (!canProbeInputFallback()) return null;
  const id = `click_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  try {
    const result = await cdp(
      "Runtime.evaluate",
      {
        expression: `(() => {
        const target = document.elementFromPoint(${JSON.stringify(point.x)}, ${JSON.stringify(point.y)});
        window.__egoBrowserInputProbes ||= {};
        const probe = { seen: false, target };
        probe.handler = (event) => {
          if (event.isTrusted && target && (event.target === target || target.contains(event.target))) {
            probe.seen = true;
          }
        };
        document.addEventListener("click", probe.handler, true);
        window.__egoBrowserInputProbes[${JSON.stringify(id)}] = probe;
        return Boolean(target);
      })()`,
        returnByValue: true,
        awaitPromise: false
      },
      point.sessionId
    );
    return result.result?.value ? id : null;
  } catch {
    return null;
  }
}
async function finishClickProbe(point, id, clickCount) {
  if (!id) return false;
  await inputEventDelay(50);
  try {
    const result = await cdp(
      "Runtime.evaluate",
      {
        expression: `(() => {
        const probes = window.__egoBrowserInputProbes || {};
        const probe = probes[${JSON.stringify(id)}];
        if (!probe) return { seen: false, fallback: false };
        document.removeEventListener("click", probe.handler, true);
        delete probes[${JSON.stringify(id)}];
        if (probe.seen || !probe.target) return { seen: probe.seen, fallback: false };
        const target = probe.target;
        const init = {
          bubbles: true,
          cancelable: true,
          view: window,
          clientX: ${JSON.stringify(point.x)},
          clientY: ${JSON.stringify(point.y)},
          button: 0,
        };
        target.dispatchEvent(new MouseEvent("mousemove", { ...init, buttons: 0, detail: 0 }));
        target.dispatchEvent(new MouseEvent("mousedown", { ...init, buttons: 1, detail: ${JSON.stringify(clickCount)} }));
        target.dispatchEvent(new MouseEvent("mouseup", { ...init, buttons: 0, detail: ${JSON.stringify(clickCount)} }));
        target.dispatchEvent(new MouseEvent("click", { ...init, buttons: 0, detail: ${JSON.stringify(clickCount)} }));
        if (${JSON.stringify(clickCount)} > 1) {
          target.dispatchEvent(new MouseEvent("dblclick", { ...init, buttons: 0, detail: 2 }));
        }
        return { seen: false, fallback: true };
      })()`,
        returnByValue: true,
        awaitPromise: false
      },
      point.sessionId
    );
    const value = result.result?.value;
    return Boolean(value?.seen || value?.fallback);
  } catch {
    return false;
  }
}
async function installMouseUpProbe(point) {
  if (!canProbeInputFallback()) return null;
  const id = `drag_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  try {
    const result = await cdp(
      "Runtime.evaluate",
      {
        expression: `(() => {
        const target = document.elementFromPoint(${JSON.stringify(point.x)}, ${JSON.stringify(point.y)});
        window.__egoBrowserInputProbes ||= {};
        const probe = { seen: false, target };
        probe.handler = (event) => {
          if (event.isTrusted && target && (event.target === target || target.contains(event.target))) {
            probe.seen = true;
          }
        };
        document.addEventListener("mouseup", probe.handler, true);
        window.__egoBrowserInputProbes[${JSON.stringify(id)}] = probe;
        return Boolean(target);
      })()`,
        returnByValue: true,
        awaitPromise: false
      },
      point.sessionId
    );
    return result.result?.value ? id : null;
  } catch {
    return null;
  }
}
async function installHoverProbe(point) {
  if (!canProbeInputFallback()) return null;
  const id = `hover_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  try {
    const result = await cdp(
      "Runtime.evaluate",
      {
        expression: `(() => {
        const target = document.elementFromPoint(${JSON.stringify(point.x)}, ${JSON.stringify(point.y)});
        window.__egoBrowserInputProbes ||= {};
        const probe = { seen: false, target };
        probe.handler = (event) => {
          if (event.isTrusted && target && (event.target === target || target.contains(event.target))) {
            probe.seen = true;
          }
        };
        document.addEventListener("mousemove", probe.handler, true);
        document.addEventListener("mouseover", probe.handler, true);
        window.__egoBrowserInputProbes[${JSON.stringify(id)}] = probe;
        return Boolean(target);
      })()`,
        returnByValue: true,
        awaitPromise: false
      },
      point.sessionId
    );
    return result.result?.value ? id : null;
  } catch {
    return null;
  }
}
async function finishHoverProbe(point, id) {
  if (!id) return false;
  await inputEventDelay(50);
  try {
    const result = await cdp(
      "Runtime.evaluate",
      {
        expression: `(() => {
        const probes = window.__egoBrowserInputProbes || {};
        const probe = probes[${JSON.stringify(id)}];
        if (!probe) return { seen: false, fallback: false };
        document.removeEventListener("mousemove", probe.handler, true);
        document.removeEventListener("mouseover", probe.handler, true);
        delete probes[${JSON.stringify(id)}];
        if (probe.seen || !probe.target) return { seen: probe.seen, fallback: false };
        const target = probe.target;
        const init = {
          bubbles: true,
          cancelable: true,
          view: window,
          clientX: ${JSON.stringify(point.x)},
          clientY: ${JSON.stringify(point.y)},
          button: 0,
          buttons: 0,
        };
        target.dispatchEvent(new MouseEvent("mousemove", init));
        target.dispatchEvent(new MouseEvent("mouseover", init));
        return { seen: false, fallback: true };
      })()`,
        returnByValue: true,
        awaitPromise: false
      },
      point.sessionId
    );
    const value = result.result?.value;
    return Boolean(value?.seen || value?.fallback);
  } catch {
    return false;
  }
}
async function finishDragProbe(points, id, button) {
  if (!id) return false;
  await inputEventDelay(50);
  const first = points[0];
  const last = points.at(-1);
  try {
    const result = await cdp(
      "Runtime.evaluate",
      {
        expression: `(() => {
        const probes = window.__egoBrowserInputProbes || {};
        const probe = probes[${JSON.stringify(id)}];
        if (!probe) return { seen: false, fallback: false };
        document.removeEventListener("mouseup", probe.handler, true);
        delete probes[${JSON.stringify(id)}];
        if (probe.seen) return { seen: true, fallback: false };
        const mouseButton = ${JSON.stringify(button === "left" ? 0 : button === "middle" ? 1 : 2)};
        const eventFor = (type, point, buttons) => {
          const target = document.elementFromPoint(point.x, point.y) || document.body;
          target.dispatchEvent(new MouseEvent(type, {
            bubbles: true,
            cancelable: true,
            view: window,
            clientX: point.x,
            clientY: point.y,
            button: mouseButton,
            buttons,
            detail: type === "mousemove" ? 0 : 1,
          }));
        };
        const points = ${JSON.stringify(points.map(({ x, y }) => ({ x, y })))};
        eventFor("mousedown", points[0], 1);
        for (const point of points.slice(1)) eventFor("mousemove", point, 1);
        eventFor("mouseup", points.at(-1), 0);
        return { seen: false, fallback: true };
      })()`,
        returnByValue: true,
        awaitPromise: false
      },
      last.sessionId ?? first.sessionId
    );
    const value = result.result?.value;
    return Boolean(value?.seen || value?.fallback);
  } catch {
    return false;
  }
}
function canProbeInputFallback() {
  return Boolean(globalThis.ego?.sendCDPMessage);
}
async function wheel(deltaX = 0, deltaY = 300, options = {}) {
  const x = numberValue(options.x ?? 0);
  const y = numberValue(options.y ?? 0);
  const dx = numberValue(deltaX);
  const dy = numberValue(deltaY);
  if (await isVisibleAndFocused()) {
    await browserCdp(
      "Input.dispatchMouseEvent",
      { type: "mouseWheel", x, y, deltaX: dx, deltaY: dy },
      void 0,
      1e3
    );
    return;
  }
  await dispatchSyntheticWheel(x, y, dx, dy);
}
async function isVisibleAndFocused() {
  try {
    return Boolean(
      await evaluate(
        "document.visibilityState === 'visible' && document.hasFocus()"
      )
    );
  } catch {
    return true;
  }
}
async function dispatchSyntheticWheel(x, y, deltaX, deltaY) {
  await evaluate(`(() => {
    const target = document.elementFromPoint(${JSON.stringify(x)}, ${JSON.stringify(y)})
      || document.scrollingElement || document.body;
    if (!target) return;
    const notPrevented = target.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true,
      cancelable: true,
      deltaX: ${JSON.stringify(deltaX)},
      deltaY: ${JSON.stringify(deltaY)},
      clientX: ${JSON.stringify(x)},
      clientY: ${JSON.stringify(y)}
    }));
    if (notPrevented) {
      window.scrollBy(${JSON.stringify(deltaX)}, ${JSON.stringify(deltaY)});
    }
  })()`);
}
async function scrollIntoViewIfNeeded(selector) {
  await resolveAndCall(
    selector,
    "function(){ if (typeof this.scrollIntoViewIfNeeded === 'function') { this.scrollIntoViewIfNeeded(true); } else { this.scrollIntoView({ block: 'center', inline: 'center' }); } }"
  );
}
function maybeHighlight(point, label) {
  const ego = globalThis.ego;
  if (!ego) return;
  ego.animationHighlightMouseToPosition?.(point.x, point.y);
  if (label) {
    ego.setAgentTaskState?.(label);
  }
}
function rememberMousePoint(point) {
  currentMousePoint = { ...point };
}
async function dispatchMouse(point, type, options = {}) {
  await browserCdp(
    "Input.dispatchMouseEvent",
    {
      type,
      x: point.x,
      y: point.y,
      ...options
    },
    point.sessionId,
    INPUT_DISPATCH_TIMEOUT_MS
  );
}
function isInputDispatchTimeout(error) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /CDP request timed out: Input\.dispatchMouseEvent/.test(message);
}
async function resolveMouseTarget(target, timeout = void 0) {
  if (typeof target === "string") {
    await waitForSelector(target, { timeout, state: "visible" });
    await scrollIntoViewIfNeeded(target);
    return elementCenter(target);
  }
  if (Array.isArray(target)) {
    return pointFrom(target);
  }
  if (target && typeof target === "object") {
    if ("selector" in target && typeof target.selector === "string" && target.selector) {
      if (target.x === void 0 && target.y === void 0) {
        await waitForSelector(target.selector, { timeout, state: "visible" });
        await scrollIntoViewIfNeeded(target.selector);
        return elementCenter(target.selector);
      }
      await waitForSelector(target.selector, { timeout, state: "visible" });
      await scrollIntoViewIfNeeded(target.selector);
      const [topLeft, center] = await Promise.all([
        elementTopLeft(target.selector),
        elementCenter(target.selector)
      ]);
      return {
        x: topLeft.x + numberValue(target.x),
        y: topLeft.y + numberValue(target.y),
        sessionId: center.sessionId
      };
    }
    if (target.x !== void 0 || target.y !== void 0) {
      return pointFrom(target);
    }
  }
  throw new Error(`invalid mouse target: ${JSON.stringify(target)}`);
}
async function elementTopLeft(selectorOrRef) {
  const { result } = await resolveAndCall(
    selectorOrRef,
    "function(){const rect=this.getBoundingClientRect();return {x:rect.left,y:rect.top};}"
  );
  const value = result.result?.value;
  if (typeof value?.x !== "number" || typeof value?.y !== "number") {
    throw new Error(`element top-left unavailable: ${selectorOrRef}`);
  }
  return { x: value.x, y: value.y };
}
function pointFrom(point) {
  const x = Array.isArray(point) ? point[0] : point?.x;
  const y = Array.isArray(point) ? point[1] : point?.y;
  if (!Number.isFinite(Number(x)) || !Number.isFinite(Number(y))) {
    throw new Error(`invalid mouse target: ${JSON.stringify(point)}`);
  }
  return { x: Number(x), y: Number(y), sessionId: void 0 };
}
function numberValue(value) {
  const out = value === void 0 ? 0 : Number(value);
  if (!Number.isFinite(out)) {
    throw new Error(`invalid mouse offset: ${JSON.stringify(value)}`);
  }
  return out;
}
function pressedButtons(button) {
  if (button === "left") {
    return 1;
  }
  if (button === "right") {
    return 2;
  }
  if (button === "middle") {
    return 4;
  }
  throw new Error(`unsupported mouse button: ${button}`);
}
export {
  click,
  dblclick,
  down,
  drag,
  hover,
  scrollIntoViewIfNeeded,
  up,
  wheel
};
