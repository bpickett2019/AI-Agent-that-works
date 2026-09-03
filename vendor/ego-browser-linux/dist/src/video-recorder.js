import { spawn } from "node:child_process";
import { mkdir, rename, unlink } from "node:fs/promises";
import { dirname } from "node:path";
const FPS = 25;
const MAX_STDERR_LENGTH = 64 * 1024;
class VideoRecorder {
  _options;
  _process;
  _exitPromise;
  _writePromise = Promise.resolve();
  _firstFrameTimestamp;
  _lastFrame;
  _lastFrameReceivedAt = 0;
  _stderr = "";
  _stdinError;
  _stopPromise;
  _tempOutputPath;
  constructor(options) {
    this._options = options;
  }
  async start() {
    const { outputPath, size } = this._options;
    await mkdir(dirname(outputPath), { recursive: true });
    this._tempOutputPath = `${outputPath}.${process.pid}-${Math.random().toString(16).slice(2)}.webm`;
    const args = [
      "-loglevel",
      "error",
      "-f",
      "image2pipe",
      "-avioflags",
      "direct",
      "-fpsprobesize",
      "0",
      "-probesize",
      "32",
      "-analyzeduration",
      "0",
      "-c:v",
      "mjpeg",
      "-i",
      "pipe:0",
      "-y",
      "-an",
      "-r",
      "25",
      "-c:v",
      "vp8",
      "-qmin",
      "0",
      "-qmax",
      "50",
      "-crf",
      "8",
      "-deadline",
      "realtime",
      "-speed",
      "8",
      "-b:v",
      "1M",
      "-threads",
      "1",
      "-vf",
      `scale=${size.width}:${size.height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=${size.width}:${size.height}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p`,
      this._tempOutputPath
    ];
    const spawnProcess = this._options.spawnProcess ?? spawn;
    this._process = spawnProcess(
      this._options.ffmpegPath ?? process.env.EGO_BROWSER_FFMPEG_PATH ?? "ffmpeg",
      args,
      { stdio: ["pipe", "ignore", "pipe"] }
    );
    this._exitPromise = new Promise((resolve) => {
      this._process.once("close", (code, signal) => resolve({ code, signal }));
      this._process.once("error", (error) => resolve({ error }));
    });
    this._process.stderr?.on("data", (chunk) => {
      this._stderr = `${this._stderr}${String(chunk)}`.slice(
        -MAX_STDERR_LENGTH
      );
    });
    this._process.stdin?.on("error", (error) => {
      this._stdinError ??= error;
    });
    try {
      await new Promise((resolve, reject) => {
        this._process.once("spawn", resolve);
        this._process.once("error", reject);
      });
    } catch (error) {
      if (error?.code === "ENOENT") {
        throw new Error(
          "FFmpeg executable was not found. Install ffmpeg or set EGO_BROWSER_FFMPEG_PATH.",
          { cause: error }
        );
      }
      throw error;
    }
  }
  writeFrame(buffer, timestamp) {
    const frameNumber = this._firstFrameTimestamp !== void 0 ? Math.floor((timestamp - this._firstFrameTimestamp) * FPS / 1e3) : 0;
    if (this._lastFrame) {
      this._queueFrames(
        this._lastFrame.buffer,
        Math.max(0, frameNumber - this._lastFrame.frameNumber)
      );
    } else {
      this._firstFrameTimestamp = timestamp;
    }
    this._lastFrame = { buffer, timestamp, frameNumber };
    this._lastFrameReceivedAt = this._now();
    return this._writePromise;
  }
  stop() {
    this._stopPromise ??= this._stop();
    return this._stopPromise;
  }
  async _stop() {
    if (this._lastFrame && this._firstFrameTimestamp !== void 0) {
      const elapsed = Math.max(this._now() - this._lastFrameReceivedAt, 1e3);
      const finalFrameNumber = Math.floor(
        (this._lastFrame.timestamp + elapsed - this._firstFrameTimestamp) * FPS / 1e3
      );
      this._queueFrames(
        this._lastFrame.buffer,
        Math.max(0, finalFrameNumber - this._lastFrame.frameNumber)
      );
    }
    let writeError;
    try {
      await this._writePromise;
    } catch (error) {
      writeError = error;
    }
    try {
      this._process.stdin.end();
    } catch (error) {
      this._stdinError ??= error;
    }
    const result = await this._exitPromise;
    const failure = result?.error ?? writeError ?? this._stdinError;
    if (failure || result?.code !== 0) {
      await this._removeTempOutput();
      const detail = this._stderr.trim();
      const status = result?.error ? result.error.message : `exited with code ${result?.code}`;
      throw new Error(`ffmpeg ${status}${detail ? `: ${detail}` : ""}`, {
        cause: failure
      });
    }
    try {
      await rename(this._tempOutputPath, this._options.outputPath);
    } catch (error) {
      await this._removeTempOutput();
      throw error;
    }
  }
  _queueFrames(buffer, count) {
    this._writePromise = this._writePromise.then(async () => {
      for (let i = 0; i < count; i++) {
        await new Promise((resolve, reject) => {
          this._process.stdin.write(
            buffer,
            (error) => error ? reject(error) : resolve()
          );
        });
      }
    });
  }
  _now() {
    return (this._options.now ?? Date.now)();
  }
  async _removeTempOutput() {
    if (!this._tempOutputPath) return;
    await unlink(this._tempOutputPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
  }
}
export {
  VideoRecorder
};
