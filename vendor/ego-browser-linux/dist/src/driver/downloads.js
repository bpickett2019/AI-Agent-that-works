import { mkdirSync } from "node:fs";
import { copyFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { cdp } from "../cdp-eval.js";
import { ensureSession, waitForBrowserEvent } from "../browser-runtime.js";
import { state } from "../state.js";
async function waitForEvent(eventName, options = {}) {
  if (eventName !== "download") {
    throw new Error(
      `page.waitForEvent currently supports only "download", got ${JSON.stringify(eventName)}`
    );
  }
  return waitForDownload(options);
}
async function waitForDownload(options = {}) {
  const timeout = options.timeout ?? state.defaultTimeout;
  const downloadDir = join(
    tmpdir(),
    `ego-browser-downloads-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
  mkdirSync(downloadDir, { recursive: true });
  const sessionPromise = ensureSession();
  const behaviorPromise = setDownloadBehavior(downloadDir);
  const willBeginPromise = waitForBrowserEvent(
    (event) => event?.method === "Page.downloadWillBegin",
    timeout
  );
  let downloadGuid;
  const progressPromise = waitForBrowserEvent(
    (event) => event?.method === "Page.downloadProgress" && (!downloadGuid || event?.params?.guid === downloadGuid) && (event?.params?.state === "completed" || event?.params?.state === "canceled"),
    timeout
  );
  await Promise.all([sessionPromise, behaviorPromise]);
  const willBegin = await willBeginPromise;
  const guid = willBegin.params?.guid;
  downloadGuid = guid;
  const suggestedFilename = willBegin.params?.suggestedFilename || guid || "download";
  const progress = await progressPromise;
  if (progress.params?.state === "canceled") {
    throw new Error(`Download canceled: ${suggestedFilename}`);
  }
  const downloadedPath = join(downloadDir, suggestedFilename);
  return {
    suggestedFilename: () => suggestedFilename,
    url: () => willBegin.params?.url || "",
    path: async () => downloadedPath,
    saveAs: async (targetPath) => {
      await copyFile(downloadedPath, targetPath);
      return targetPath;
    }
  };
}
async function setDownloadBehavior(downloadDir) {
  try {
    await cdp("Browser.setDownloadBehavior", {
      behavior: "allow",
      downloadPath: downloadDir,
      eventsEnabled: true
    });
  } catch (error) {
    if (!/Browser\.setDownloadBehavior.*wasn't found|wasn't found/i.test(
      error?.message || ""
    )) {
      throw error;
    }
    await cdp("Page.setDownloadBehavior", {
      behavior: "allow",
      downloadPath: downloadDir
    });
  }
}
export {
  waitForEvent
};
