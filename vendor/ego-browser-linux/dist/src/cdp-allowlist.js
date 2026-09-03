const BLOCKED_CDP_METHODS = /* @__PURE__ */ new Set([
  // File system access — can read arbitrary local files
  "IO.read",
  "IO.close",
  "IO.readU8Array",
  // Browser lifecycle — can crash/close the browser
  "Browser.close",
  "Browser.crash",
  "Browser.crashGpuProcess",
  // System info — fingerprinting
  "SystemInfo.getInfo",
  "SystemInfo.getProcessInfo",
  // DevTools extensions — can inject code into DevTools
  "DevToolsExtensions.addExtension",
  // Tracing — can capture all browser activity
  "Tracing.start",
  "Tracing.end",
  "Tracing.recordClockSyncMarker",
  // Tethering — can expose ports
  "Tethering.start",
  "Tethering.stop"
]);
const BLOCKED_CDP_PREFIXES = [
  "IO.",
  "SystemInfo.",
  "Tethering.",
  "DevToolsExtensions."
];
function isCdpMethodAllowed(method) {
  if (BLOCKED_CDP_METHODS.has(method)) return false;
  for (const prefix of BLOCKED_CDP_PREFIXES) {
    if (method.startsWith(prefix)) return false;
  }
  return true;
}
function assertCdpMethodAllowed(method) {
  if (!isCdpMethodAllowed(method)) {
    throw new Error(
      `CDP method ${method} is blocked by the security allowlist. This is a safety measure to prevent file system access, browser crashes, and system fingerprinting.`
    );
  }
}
export {
  assertCdpMethodAllowed,
  isCdpMethodAllowed
};
