import { resolve } from "node:path";
import {
  browserCdp,
  ensureSession,
  subscribeBrowserEvent
} from "../browser-runtime.js";
import { VideoRecorder } from "../video-recorder.js";
import { pageInfo } from "./nav.js";
const defaults = {
  browserCdp,
  ensureSession,
  pageInfo,
  subscribeBrowserEvent,
  createRecorder: (options) => new VideoRecorder(options),
  now: Date.now
};
let dependencies = { ...defaults };
let activeRecording;
async function startScreencast(options) {
  if (!options || typeof options.path !== "string" || !options.path.endsWith(".webm")) {
    throw new Error("page.screencast.start path must end with .webm");
  }
  const quality = options.quality ?? 90;
  if (!Number.isInteger(quality) || quality < 0 || quality > 100) {
    throw new Error("page.screencast.start quality must be between 0 and 100");
  }
  if (options.size && (!Number.isInteger(options.size.width) || !Number.isInteger(options.size.height) || options.size.width < 2 || options.size.height < 2)) {
    throw new Error(
      "page.screencast.start width and height must be at least 2 pixels"
    );
  }
  if (activeRecording) throw new Error("Screencast is already started");
  const sessionId = await dependencies.ensureSession();
  const size = evenSize(options.size ?? await defaultSize());
  const recorder = dependencies.createRecorder({
    outputPath: resolve(options.path),
    size
  });
  await recorder.start();
  const recording = {
    sessionId,
    recorder,
    unsubscribe: () => {
    },
    receivedFrames: false,
    quality,
    frameChain: Promise.resolve()
  };
  activeRecording = recording;
  try {
    recording.unsubscribe = dependencies.subscribeBrowserEvent(
      "Page.screencastFrame",
      sessionId,
      (event) => {
        recording.receivedFrames = true;
        recording.frameChain = recording.frameChain.then(async () => {
          const cdpTimestamp = event.params?.metadata?.timestamp;
          const timestamp = typeof cdpTimestamp === "number" ? cdpTimestamp * 1e3 : dependencies.now();
          await recorder.writeFrame(
            Buffer.from(event.params.data, "base64"),
            timestamp
          );
          await dependencies.browserCdp(
            "Page.screencastFrameAck",
            { sessionId: event.params.sessionId },
            sessionId
          );
        }).catch((error) => {
          recording.error ??= error;
        });
      }
    );
    await dependencies.browserCdp(
      "Page.startScreencast",
      {
        format: "jpeg",
        quality,
        maxWidth: size.width,
        maxHeight: size.height
      },
      sessionId
    );
  } catch (error) {
    activeRecording = void 0;
    recording.unsubscribe();
    await recorder.stop().catch(() => {
    });
    throw error;
  }
  const dispose = async () => {
    if (activeRecording === recording) await stopScreencast();
  };
  return { dispose, [Symbol.asyncDispose]: dispose };
}
async function stopScreencast() {
  const recording = activeRecording;
  if (!recording) return;
  activeRecording = void 0;
  let stopError = recording.error;
  recording.unsubscribe();
  await recording.frameChain;
  stopError ??= recording.error;
  try {
    if (!recording.receivedFrames) {
      const response = await dependencies.browserCdp(
        "Page.captureScreenshot",
        { format: "jpeg", quality: recording.quality },
        recording.sessionId
      );
      const data = response.result?.data ?? response.data;
      await recording.recorder.writeFrame(
        Buffer.from(data, "base64"),
        dependencies.now()
      );
    }
  } catch (error) {
    stopError ??= error;
  }
  try {
    await dependencies.browserCdp(
      "Page.stopScreencast",
      {},
      recording.sessionId
    );
  } catch (error) {
    stopError ??= error;
  }
  try {
    await recording.recorder.stop();
  } catch (error) {
    stopError ??= error;
  }
  if (stopError) throw stopError;
}
async function defaultSize() {
  const info = await dependencies.pageInfo();
  const scale = Math.min(1, 800 / Math.max(info.w, info.h));
  return evenSize({
    width: Math.floor(info.w * scale),
    height: Math.floor(info.h * scale)
  });
}
function evenSize(size) {
  return { width: size.width & ~1, height: size.height & ~1 };
}
const __testing = {
  setOverrides(overrides) {
    const previous = dependencies;
    dependencies = { ...dependencies, ...overrides };
    return () => {
      dependencies = previous;
    };
  }
};
export {
  __testing,
  startScreencast,
  stopScreencast
};
