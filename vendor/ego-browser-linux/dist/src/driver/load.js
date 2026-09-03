import { cdp, evaluate } from "../cdp-eval.js";
import { state } from "../state.js";
async function waitForDocumentLoad(options = {}) {
  const timeout = options.timeout ?? 15e3;
  const ready = options.until === "domcontentloaded" ? ["interactive", "complete"] : ["complete"];
  const deadline = state.now() + timeout;
  while (state.now() < deadline) {
    let committed = true;
    try {
      const tree = await cdp("Page.getFrameTree");
      const url = tree.frameTree?.frame?.url || "";
      committed = url !== "" && url !== ":" && url !== "about:blank";
    } catch {
    }
    if (committed && ready.includes(await evaluate("document.readyState"))) {
      return true;
    }
    await state.sleep(300);
  }
  return false;
}
export {
  waitForDocumentLoad
};
