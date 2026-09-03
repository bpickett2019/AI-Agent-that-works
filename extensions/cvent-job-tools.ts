import { execFile } from "node:child_process";
import { randomUUID, createHash } from "node:crypto";
import { open, readFile, realpath, rename, mkdir, appendFile, lstat } from "node:fs/promises";
import { join, resolve } from "node:path";
import { Type } from "typebox";

const BROWSER_OPERATION_NAMES = [
  "probe", "authorizeTarget", "openAuthorizedEvent", "snapshotText", "controlInventory", "pageInfo", "scanEventList",
  "scroll", "click", "activate", "fill", "type", "navigate", "wait", "hover",  "selectOption", "setChecked", "press", "search", "selectText", "drag",
];
const BROWSER_OPERATIONS = new Set(BROWSER_OPERATION_NAMES);
const READ_ONLY_OPERATIONS = new Set([
  "probe", "authorizeTarget", "openAuthorizedEvent", "snapshotText", "controlInventory", "pageInfo", "scanEventList",
  "scroll", "navigate", "wait", "hover", "search", "selectText",]);
const ALLOWED_KEYS = new Set([
  "Enter", "Escape", "Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
  "Backspace", "Delete", "Home", "End", "PageUp", "PageDown", "Space",
]);
const DOMAINS = new Set([
  "event_basics", "theme_branding", "header_footer_body", "registration_paths",
  "registration_types", "admission_items", "pricing_fees", "discounts",
  "registration_questions", "terms_policies", "final_qa",
]);
const ARTIFACTS: Record<string, string> = {
  state: "state.json",
  auth_metadata: "auth-settings.json",
  target_lock: "authorized-target.json",
  activity: "activity.log",
  write_audit: "scope-write-audit.jsonl",
  final_report: "final-report.json",
  domain_results: "domain-results.json",
  inspection_summary: "input.inspection-summary.json",
  browser_runtime: "browser-runtime.json",
};
const ALLOWED_TOOLS = new Set([
  "cvent_prepare_rr", "cvent_expectations", "cvent_scope", "cvent_job_read",
  "cvent_job_update", "cvent_record_domain", "cvent_browser",
  "cvent_login_handoff", "cvent_snapshot_chunk", "cvent_finish",
]);
const MAX_TEXT_BYTES = 48 * 1024;
const SNAPSHOT_CHUNK_BYTES = 36 * 1024;
const MAX_CHILD_OUTPUT = 8 * 1024 * 1024;
const MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024;
const SNAPSHOT_PENDING = join(resolve(requiredEnvironment("CVENT_JOB_DIR")), "browser-snapshot-pending.json");
const queues = new Map<string, Promise<unknown>>();

function requiredEnvironment(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Required server capability ${name} is absent`);
  return value;
}

const jobDir = resolve(requiredEnvironment("CVENT_JOB_DIR"));
const repoRoot = resolve(requiredEnvironment("CVENT_REPO_ROOT"));
const runtimePath = join(jobDir, "browser-runtime.json");
const python = process.env.CVENT_PYTHON || "python3";

function assertFixedJobPath(path: string): string {
  const absolute = resolve(path);
  if (absolute !== jobDir && !absolute.startsWith(jobDir + "/")) {
    throw new Error("Capability denied: path is outside this job workspace");
  }
  return absolute;
}

function cleanText(value: unknown, max = 4000): string {
  const text = String(value ?? "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "").trim();
  return text.slice(0, max);
}

function redact(text: string): string {
  let value = text.replace(/((?:ANTHROPIC_API_KEY|CVENT_LEASE_TOKEN|ENTRA_CLIENT_SECRET|CVENT_SESSION_SECRET)\s*[=:]\s*)\S+/gi, "$1[REDACTED]");
  for (const name of ["ANTHROPIC_API_KEY", "CVENT_LEASE_TOKEN", "ENTRA_CLIENT_SECRET", "CVENT_SESSION_SECRET", "AZURE_CLIENT_SECRET"]) {
    const secret = process.env[name];
    if (secret && secret.length >= 8) value = value.split(secret).join("[REDACTED]");
  }
  return value.slice(-MAX_TEXT_BYTES);
}

function toolText(value: unknown): { content: Array<{ type: "text"; text: string }>; details: Record<string, unknown> } {
  let text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (Buffer.byteLength(text, "utf8") > MAX_TEXT_BYTES) {
    text = utf8Chunks(text, MAX_TEXT_BYTES)[0] +
      "\n[Capability output stopped at 48KB; request a narrower domain/page. No source read was shortened.]";
  }
  return { content: [{ type: "text", text }], details: {} };
}

function safeChildEnvironment(kind: "browser" | "prepare"): NodeJS.ProcessEnv {
  const names = ["PATH", "LANG", "LC_ALL", "TZ"];
  const environment: NodeJS.ProcessEnv = {};
  for (const name of names) if (process.env[name]) environment[name] = process.env[name];
  environment.CVENT_REPO_ROOT = repoRoot;
  environment.CVENT_JOB_DIR = jobDir;
  for (const name of [
    "CVENT_ENV", "CVENT_JOB_ID", "CVENT_WORKSPACE_ID", "CVENT_WORKER_SLOT",
    "CVENT_STEEL_API_ORIGIN", "CVENT_CDP_ORIGIN", "CVENT_AUTHORIZED_EVENT_ID",
    "CVENT_AUTHORIZED_EVENT_NAME", "CVENT_AUTHORIZED_EVENT_KEY", "CVENT_AUTHORIZED_EVENT_CODE",
  ]) if (process.env[name]) environment[name] = process.env[name];
  if (kind === "browser") {
    environment.CVENT_LEASE_VALIDATE_URL = requiredEnvironment("CVENT_LEASE_VALIDATE_URL");
    environment.CVENT_LEASE_TOKEN = requiredEnvironment("CVENT_LEASE_TOKEN");
  }
  return environment;
}

function runFixed(executable: string, args: string[], kind: "browser" | "prepare", signal?: AbortSignal, timeout = 120000): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolvePromise, rejectPromise) => {
    execFile(executable, args, {
      cwd: repoRoot,
      env: safeChildEnvironment(kind),
      timeout,
      maxBuffer: MAX_CHILD_OUTPUT,
      signal,
      windowsHide: true,
    }, (error, stdout, stderr) => {
      if (error) {
        rejectPromise(new Error(redact(`${error.message}\n${stderr || stdout}`)));
        return;
      }
      resolvePromise({ stdout: String(stdout), stderr: String(stderr) });
    });
  });
}

async function withQueue<T>(key: string, operation: () => Promise<T>): Promise<T> {
  const previous = queues.get(key) ?? Promise.resolve();
  let release!: () => void;
  const current = new Promise<void>((resolvePromise) => { release = resolvePromise; });
  const tail = previous.catch(() => undefined).then(() => current);
  queues.set(key, tail);
  await previous.catch(() => undefined);
  try {
    return await operation();
  } finally {
    release();
    if (queues.get(key) === tail) queues.delete(key);
  }
}

async function assertPrivateJobRoot(): Promise<void> {
  const canonical = await realpath(jobDir);
  if (canonical !== jobDir) throw new Error("Capability denied: job workspace may not be a symlink");
}

async function readJobFile(path: string, maxBytes = MAX_CHILD_OUTPUT): Promise<Buffer> {
  await assertPrivateJobRoot();
  const target = assertFixedJobPath(path);
  const info = await lstat(target);
  if (!info.isFile() || info.isSymbolicLink()) throw new Error("Capability denied: job artifact must be a regular non-symlink file");
  if (info.size > maxBytes) throw new Error("Capability denied: job artifact exceeds its read limit");
  return readFile(target);
}

async function readJson(path: string, fallback: unknown = {}): Promise<any> {
  try { return JSON.parse((await readJobFile(path)).toString("utf8")); }
  catch (error: any) {
    if (error?.code === "ENOENT") return fallback;
    throw error;
  }
}

async function atomicJson(path: string, value: unknown): Promise<void> {
  await assertPrivateJobRoot();
  const target = assertFixedJobPath(path);
  await mkdir(jobDir, { recursive: true, mode: 0o700 });
  const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(JSON.stringify(value, null, 2) + "\n", "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await rename(temporary, target);
}

async function assertSafeArtifactTarget(path: string): Promise<string> {
  await assertPrivateJobRoot();
  const target = assertFixedJobPath(path);
  try {
    const info = await lstat(target);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error("Capability denied: job artifact target is not a regular file");
  } catch (error: any) {
    if (error?.code !== "ENOENT") throw error;
  }
  return target;
}

async function appendActivity(message: string): Promise<void> {
  const safe = cleanText(message, 1200).replace(/[\r\n]+/g, " ");
  if (!safe) return;
  const target = await assertSafeArtifactTarget(join(jobDir, "activity.log"));
  await appendFile(target, `${new Date().toISOString()}  ${safe}\n`, { encoding: "utf8", mode: 0o600 });
}

function hash(buffer: Buffer): string {
  return createHash("sha256").update(buffer).digest("hex");
}

async function verifiedScope(): Promise<any> {
  const manifestPath = join(repoRoot, "scope", "intake-emerald-scope.json");
  const workbookPath = join(repoRoot, "scope", "intake-emerald.xlsx");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const actual = hash(await readFile(workbookPath));
  if (!manifest.sourceSha256 || manifest.sourceSha256 !== actual) {
    throw new Error("Forge Intake scope workbook and manifest do not match");
  }
  return manifest;
}

function parseMarker(stdout: string, marker: string): any {
  const line = stdout.split(/\r?\n/).reverse().find((item) => item.startsWith(marker));
  if (!line) throw new Error("Approved helper returned no structured result");
  const result = JSON.parse(line.slice(marker.length));
  if (!result?.ok) throw new Error(redact(result?.error || "Approved helper failed"));
  return result;
}

async function invokeBrowser(operation: string, params: Record<string, unknown>, signal?: AbortSignal, timeoutSeconds = 90): Promise<any> {
  await readJobFile(runtimePath, 1024 * 1024);
  const timeout = Math.max(1, Math.min(timeoutSeconds, 180));
  const boundedParams = { ...params, timeoutSeconds: timeout };
  const output = await runFixed(python, [
    join(repoRoot, "browser_tool.py"), "--runtime", runtimePath, "--tool", "ego",
    "--operation", operation, "--params", JSON.stringify(boundedParams),
  ], "browser", signal, (timeout + 10) * 1000);
  return parseMarker(output.stdout, "BROWSER_ROUTER_RESULT=");
}

function browserParams(operation: string, input: any): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (["authorizeTarget", "openAuthorizedEvent"].includes(operation)) {
    params.eventName = requiredEnvironment("CVENT_AUTHORIZED_EVENT_NAME");
    params.eventKey = requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY");
  }
  if (operation === "scanEventList") {
    params.exactName = requiredEnvironment("CVENT_AUTHORIZED_EVENT_NAME");
    params.maxScrolls = Math.max(1, Math.min(Number(input.maxScrolls ?? 30), 60));
  }
  if (["click", "activate", "fill", "type", "hover", "selectOption", "setChecked", "press", "search", "selectText", "drag", "wait"].includes(operation) && input.target) {
    params.target = cleanText(input.target, 4000);
  }
  if (["fill", "type", "search"].includes(operation)) params.text = cleanText(input.text, 20000);
  if (operation === "selectOption") {
    params.option = cleanText(input.option, 2000);
    params.optionBy = input.optionBy === "value" ? "value" : "label";
  }
  if (operation === "setChecked") params.checked = Boolean(input.checked);
  if (operation === "press") params.key = cleanText(input.key, 40);
  if (operation === "search") params.submit = input.submit !== false;
  if (operation === "drag") params.destination = cleanText(input.destination, 4000);
  if (operation === "navigate") params.url = cleanText(input.url, 8000);
  if (operation === "scroll") {
    params.deltaY = Math.max(-10000, Math.min(Number(input.deltaY ?? 700), 10000));
    params.settleMs = Math.max(100, Math.min(Number(input.settleMs ?? 500), 5000));
  }
  if (operation === "wait") {
    params.ms = Math.max(50, Math.min(Number(input.ms ?? 1000), 30000));
    if (["load", "domcontentloaded", "networkidle"].includes(input.loadState)) params.loadState = input.loadState;
  }
  params.intent = input.intent;
  if (input.intent === "write") params.scopeIds = input.scopeIds;
  return params;
}

function utf8Chunks(text: string, maxBytes: number): string[] {
  const chunks: string[] = [];
  let current = "";
  let currentBytes = 0;
  for (const character of text) {
    const size = Buffer.byteLength(character, "utf8");
    if (current && currentBytes + size > maxBytes) {
      chunks.push(current);
      current = "";
      currentBytes = 0;
    }
    current += character;
    currentBytes += size;
  }
  if (current || chunks.length === 0) chunks.push(current);
  return chunks;
}

async function pendingSnapshot(): Promise<any> {
  return readJson(SNAPSHOT_PENDING, null);
}

async function assertSnapshotConsumed(): Promise<void> {
  const pending = await pendingSnapshot();
  if (pending && pending.complete !== true) {
    throw new Error(`Complete snapshot ${pending.snapshotId} is not fully consumed; request chunk ${pending.nextChunk} before another browser action`);
  }
}

async function saveLargeSnapshot(result: any): Promise<any> {
  const snapshot = result?.snapshot;
  if (typeof snapshot !== "string") return result;
  const bytes = Buffer.byteLength(snapshot, "utf8");
  if (bytes > MAX_SNAPSHOT_BYTES) throw new Error("Complete DOM snapshot exceeds the 2MB fail-closed transport limit");
  const digest = hash(Buffer.from(snapshot, "utf8"));
  result.snapshotMetadata = {
    bytes, sha256: digest, capturedAt: result.observedAt, browserRuntimeId: result.browserRuntimeId,
    workerSlot: Number(requiredEnvironment("CVENT_WORKER_SLOT")), targetId: result.targetId,
    jobId: requiredEnvironment("CVENT_JOB_ID"), workspaceId: requiredEnvironment("CVENT_WORKSPACE_ID"),
    url: result.page?.url, title: result.page?.title,
  };
  if (bytes <= SNAPSHOT_CHUNK_BYTES) return result;
  const id = randomUUID();
  const directory = assertFixedJobPath(join(jobDir, "browser-snapshots"));
  await assertPrivateJobRoot();
  try {
    const info = await lstat(directory);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("Capability denied: snapshot directory is not private");
  } catch (error: any) {
    if (error?.code !== "ENOENT") throw error;
    await mkdir(directory, { mode: 0o700 });
  }
  const path = assertFixedJobPath(join(directory, `${id}.txt`));
  const handle = await open(path, "wx", 0o600);
  try { await handle.writeFile(snapshot, "utf8"); } finally { await handle.close(); }
  const chunks = utf8Chunks(snapshot, SNAPSHOT_CHUNK_BYTES);
  const transport = {
    ...result.snapshotMetadata, snapshotId: id, totalChunks: chunks.length,
    nextChunk: 1, complete: false,
  };
  await atomicJson(SNAPSHOT_PENDING, transport);
  delete result.snapshot;
  result.completeSnapshot = {
    ...result.snapshotMetadata, snapshotId: id, totalChunks: chunks.length,
    chunkIndex: 0, complete: false, chunkText: chunks[0],
    instruction: "Read every remaining chunk with cvent_snapshot_chunk in strict order before another browser action.",
  };
  return result;
}

export const __capabilityTest = { utf8Chunks, saveLargeSnapshot, pendingSnapshot, assertSnapshotConsumed };

function pageArrays(value: any, offset: number, limit: number): any {
  if (Array.isArray(value)) return value.slice(offset, offset + limit).map((item) => pageArrays(item, 0, limit));
  if (!value || typeof value !== "object") return value;
  const result: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(value)) {
    if (Array.isArray(child)) {
      result[key] = child.slice(offset, offset + limit);
      result[`${key}Pagination`] = { offset, returned: Math.min(limit, Math.max(0, child.length - offset)), total: child.length };
    } else result[key] = child;
  }
  return result;
}

const optionalStrings = Type.Optional(Type.Array(Type.String({ maxLength: 2000 }), { maxItems: 200 }));

export default function cventJobTools(pi: any) {
  pi.on("session_start", () => pi.setActiveTools([...ALLOWED_TOOLS]));
  pi.on("before_agent_start", () => pi.setActiveTools([...ALLOWED_TOOLS]));
  pi.on("tool_call", (event: any) => {
    if (!ALLOWED_TOOLS.has(event.toolName)) {
      return { block: true, reason: "Capability denied: this production agent has no shell or general filesystem tools" };
    }
    return undefined;
  });

  pi.registerTool({
    name: "cvent_prepare_rr",
    label: "Prepare RR",
    description: "Verify Forge Intake, inspect the fixed job RR workbook, and compile confirmed job-scoped expectations using approved server helpers. Takes no paths or commands.",
    parameters: Type.Object({}),
    async execute(_id: string, _params: unknown, signal: AbortSignal) {
      return withQueue("job-files", async () => {
        await verifiedScope();
        await readJobFile(join(jobDir, "input.xlsx"), 25 * 1024 * 1024);
        await assertSafeArtifactTarget(join(jobDir, "input.inspection.json"));
        await assertSafeArtifactTarget(join(jobDir, "input.inspection-summary.json"));
        await assertSafeArtifactTarget(join(jobDir, "expected-domains.json"));
        await runFixed(python, [join(repoRoot, "inspect_rr.py"), join(jobDir, "input.xlsx"), join(jobDir, "input.inspection.json")], "prepare", signal, 180000);
        const compiled = await runFixed(python, [join(repoRoot, "rr_compiler.py")], "prepare", signal, 180000);
        const result = JSON.parse(compiled.stdout);
        await appendActivity(`RR normalized to ${result.counts?.confirmedApplicableFields ?? 0} confirmed applicable fields`);
        return toolText(result);
      });
    },
  });

  pi.registerTool({
    name: "cvent_expectations",
    label: "Read RR expectations",
    description: "Read only normalized confirmed expectations for one approved domain, or summary/excluded/identifiers. Large record arrays are paged without rereading or narrowing the source workbook.",
    parameters: Type.Object({
      section: Type.String({ description: "summary, excluded, identifiers, or an approved domain name" }),
      offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000 })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 25 })),
    }),
    async execute(_id: string, params: any) {
      const expected = await readJson(join(jobDir, "expected-domains.json"), null);
      if (!expected) throw new Error("Run cvent_prepare_rr first");
      const section = String(params.section);
      let value: any;
      if (section === "summary") value = { rr: expected.rr, scope: expected.scope, target: expected.target, counts: expected.counts };
      else if (section === "excluded") value = expected.excludedOrBlocked;
      else if (section === "identifiers") value = expected.identifierRegistry;
      else if (DOMAINS.has(section)) value = expected.domains?.[section];
      else throw new Error("Capability denied: unknown expectation section");
      return toolText(pageArrays(value, params.offset ?? 0, params.limit ?? 10));
    },
  });

  pi.registerTool({
    name: "cvent_scope",
    label: "Read verified scope",
    description: "Read hash-verified Forge Intake entries, filtered to supplied scope IDs or a section. This never reads arbitrary files.",
    parameters: Type.Object({
      scopeIds: Type.Optional(Type.Array(Type.String({ pattern: "^scope-[0-9]{3}$" }), { maxItems: 100 })),
      section: Type.Optional(Type.String({ maxLength: 200 })),
    }),
    async execute(_id: string, params: any) {
      const manifest = await verifiedScope();
      const ids = new Set(params.scopeIds ?? []);
      const section = cleanText(params.section ?? "", 200).toLowerCase();
      let entries = manifest.entries;
      if (ids.size) entries = entries.filter((entry: any) => ids.has(entry.id));
      if (section) entries = entries.filter((entry: any) => String(entry.section ?? "").toLowerCase().includes(section));
      if (!ids.size && !section) entries = entries.filter((entry: any) => entry.status === "confirmed");
      return toolText({ authority: manifest.authority, sourceSha256: manifest.sourceSha256, counts: manifest.counts, entries });
    },
  });

  pi.registerTool({
    name: "cvent_job_read",
    label: "Read job artifact",
    description: "Read one fixed safe job artifact: state, auth_metadata, target_lock, activity, write_audit, final_report, domain_results, inspection_summary, or browser_runtime. No path input is accepted.",
    parameters: Type.Object({
      artifact: Type.String(),
      tailLines: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
    }),
    async execute(_id: string, params: any) {
      const relative = ARTIFACTS[String(params.artifact)];
      if (!relative) throw new Error("Capability denied: artifact is not approved");
      const path = assertFixedJobPath(join(jobDir, relative));
      let text: string;
      try { text = (await readJobFile(path)).toString("utf8"); }
      catch (error: any) {
        if (error?.code === "ENOENT") return toolText({ exists: false, artifact: params.artifact });
        throw error;
      }
      if (["activity", "write_audit"].includes(String(params.artifact))) {
        const lines = text.split(/\r?\n/);
        text = lines.slice(-(params.tailLines ?? 100)).join("\n");
      } else if (params.artifact === "browser_runtime") {
        const value = JSON.parse(text);
        text = JSON.stringify({
          browserRuntimeId: value.browserRuntimeId,
          workerSlot: value.workerSlot,
          viewerUrl: value.viewerUrl,
          authorizedEventName: value.authorizedEventName,
          authorizedEventId: value.authorizedEventId,
          authorizedEventKey: value.authorizedEventKey,
          targetBrowserIdentity: {
            targetId: value.targetBrowserIdentity?.targetId,
            marker: value.targetBrowserIdentity?.marker,
            url: value.targetBrowserIdentity?.url,
            title: value.targetBrowserIdentity?.title,
          },
          verifiedAt: value.verifiedAt,
        }, null, 2);
      }
      return toolText(text);
    },
  });

  pi.registerTool({
    name: "cvent_job_update",
    label: "Update job progress",
    description: "Atomically update only approved progress fields in this job's state and append one safe product-facing log message. Cannot select paths or execute commands.",
    parameters: Type.Object({
      status: Type.Optional(Type.String({ maxLength: 40 })),
      stage: Type.Optional(Type.String({ maxLength: 80 })),
      action: Type.Optional(Type.String({ maxLength: 1200 })),
      completed: Type.Optional(Type.Array(Type.String({ maxLength: 80 }), { maxItems: 20 })),
      pending: Type.Optional(Type.Array(Type.String({ maxLength: 80 }), { maxItems: 20 })),
      reviewRequired: optionalStrings,
      log: Type.Optional(Type.String({ maxLength: 1200 })),
    }),
    async execute(_id: string, params: any) {
      return withQueue("job-files", async () => {
        const allowedStatuses = new Set(["running", "login_required", "review_required"]);
        if (params.status && !allowedStatuses.has(params.status)) throw new Error("Capability denied: invalid progress status");
        if (params.stage && !DOMAINS.has(params.stage) && !["starting", "target_discovery", "queued"].includes(params.stage)) {
          throw new Error("Capability denied: invalid job stage");
        }
        const path = join(jobDir, "state.json");
        const state = await readJson(path, {});
        if (params.status) state.status = params.status;
        if (params.stage) state.current_stage = params.stage;
        if (params.action) state.current_action = cleanText(params.action, 1200);
        if (params.completed) state.completed = params.completed;
        if (params.pending) state.pending = params.pending;
        if (params.reviewRequired) state.review_required = params.reviewRequired.map((item: unknown) => cleanText(item, 2000));
        state.updated_at = new Date().toISOString();
        await atomicJson(path, state);
        if (params.log) await appendActivity(params.log);
        return toolText({ ok: true, status: state.status, stage: state.current_stage, action: state.current_action });
      });
    },
  });

  pi.registerTool({
    name: "cvent_record_domain",
    label: "Record domain result",
    description: "Atomically record factual job-scoped results for one approved domain. This cannot write arbitrary files.",
    parameters: Type.Object({
      domain: Type.String(),
      status: Type.String({ maxLength: 40 }),
      created: optionalStrings,
      updated: optionalStrings,
      alreadyCorrect: optionalStrings,
      verifiedReads: optionalStrings,
      verifiedWrites: optionalStrings,
      blocked: optionalStrings,
    }),
    async execute(_id: string, params: any) {
      if (!DOMAINS.has(params.domain)) throw new Error("Capability denied: unknown domain");
      if (!["in_progress", "completed", "review_required", "incomplete"].includes(params.status)) throw new Error("Capability denied: invalid domain status");
      return withQueue("job-files", async () => {
        const path = join(jobDir, "domain-results.json");
        const document = await readJson(path, { schemaVersion: 1, domains: {} });
        document.domains ??= {};
        document.domains[params.domain] = {
          status: params.status,
          created: params.created ?? [],
          updated: params.updated ?? [],
          already_correct: params.alreadyCorrect ?? [],
          verified_reads: params.verifiedReads ?? [],
          verified_writes: params.verifiedWrites ?? [],
          blocked: params.blocked ?? [],
          updated_at: new Date().toISOString(),
        };
        document.updatedAt = new Date().toISOString();
        await atomicJson(path, document);
        return toolText({ ok: true, domain: params.domain, status: params.status });
      });
    },
  });

  pi.registerTool({
    name: "cvent_login_handoff",
    label: "Request Cvent login",
    description: "Open the fixed Cvent subscriber entry point when the browser is blank, detect a login page, and hand this job's existing Steel viewer to the user for SSO/MFA. If already authenticated, return without handing off; otherwise wait until the user returns control.",
    parameters: Type.Object({}),
    async execute(_id: string, _params: unknown, signal: AbortSignal) {
      return withQueue("browser", async () => {
        let pageResult = await invokeBrowser("pageInfo", { intent: "read" }, signal, 45);
        let pageUrl = String(pageResult?.page?.url ?? "");
        let pageTitle = String(pageResult?.page?.title ?? "");
        let host = "";
        try { host = new URL(pageUrl).hostname.toLowerCase(); } catch { /* fixed navigation below */ }
        const recognizedLoginHost = host.endsWith("cvent.com") || host.includes("microsoftonline.com") || host.includes("login.windows.net") || host.includes("login.live.com");
        if (!pageUrl || pageUrl === "about:blank" || !recognizedLoginHost) {
          await invokeBrowser("navigate", { intent: "read", url: "https://app.cvent.com/subscribers/default.aspx" }, signal, 60);
          pageResult = await invokeBrowser("pageInfo", { intent: "read" }, signal, 45);
          pageUrl = String(pageResult?.page?.url ?? "");
          pageTitle = String(pageResult?.page?.title ?? "");
          try { host = new URL(pageUrl).hostname.toLowerCase(); } catch { host = ""; }
        }
        const needsLogin = host.includes("microsoftonline.com") || host.includes("login.windows.net") || host.includes("login.live.com") || /(?:login|sign.?in|sso|authenticate)/i.test(`${pageUrl} ${pageTitle}`);
        if (!needsLogin) {
          return toolText({ ok: true, loginRequired: false, url: pageUrl, instruction: "The browser is not on a login page; fresh-read a complete snapshot and continue." });
        }

        const gatePath = join(jobDir, "browser-gate.json");
        const gate = await readJson(gatePath, {});
        if (gate.ownership !== "AGENT" || gate.desiredOwnership !== "AGENT" || ![undefined, null, "NONE"].includes(gate.activeActor)) {
          throw new Error("Login handoff requires an idle agent-owned browser gate");
        }
        const statePath = join(jobDir, "state.json");
        const state = await readJson(statePath, {});
        state.status = "login_required";
        state.current_stage = "login_required";
        state.current_action = "Complete Cvent SSO/MFA in the browser, save login info, then return control to the agent";
        state.updated_at = new Date().toISOString();
        await atomicJson(statePath, state);
        gate.ownership = "USER";
        gate.desiredOwnership = "USER";
        gate.activeActor = "USER";
        gate.automationOwner = "USER";
        gate.agentPaused = true;
        gate.pausedPids = [process.pid];
        gate.transition = null;
        gate.updatedAt = new Date().toISOString();
        await atomicJson(gatePath, gate);
        await appendActivity("Cvent login required; browser control handed to user for SSO/MFA");

        const deadline = Date.now() + 30 * 60 * 1000;
        while (Date.now() < deadline) {
          if (signal?.aborted) throw new Error("Login handoff cancelled");
          await new Promise((resolvePromise) => setTimeout(resolvePromise, 1000));
          const current = await readJson(gatePath, {});
          if (current.ownership === "AGENT" && current.desiredOwnership === "AGENT") {
            const resumed = await readJson(statePath, {});
            resumed.status = "running";
            resumed.current_stage = "target_discovery";
            resumed.current_action = "Verifying Cvent login and resuming exact-event discovery";
            resumed.updated_at = new Date().toISOString();
            await atomicJson(statePath, resumed);
            await appendActivity("User returned browser control; verifying Cvent login before resuming");
            return toolText({ ok: true, resumed: true, instruction: "Fresh-read pageInfo and a complete snapshot before continuing." });
          }
          if (current.ownership === "NONE") throw new Error("Browser return was blocked; human review is required");
        }
        throw new Error("Cvent login handoff timed out after 30 minutes");
      });
    },
  });

  pi.registerTool({
    name: "cvent_browser",
    label: "Cvent browser",
    description: "Perform one validated, structurally bounded Ego operation in this job's canonical Steel browser: complete reads, navigation/waits, click/fill/type, select/check/key/search, hover/text-selection, or source-to-destination drag. Server-forced target identity, current event lease, write scope IDs, browser ownership, and Cvent-only navigation are enforced. There is no command, script, CDP payload, or path capability.",
    parameters: Type.Object({
      operation: Type.Union(BROWSER_OPERATION_NAMES.map((name) => Type.Literal(name))),
      intent: Type.Union([Type.Literal("read"), Type.Literal("write")]),
      scopeIds: Type.Optional(Type.Array(Type.String({ pattern: "^scope-[0-9]{3}$" }), { maxItems: 100 })),
      target: Type.Optional(Type.String({ maxLength: 4000 })),
      text: Type.Optional(Type.String({ maxLength: 20000 })),
      url: Type.Optional(Type.String({ maxLength: 8000 })),
      option: Type.Optional(Type.String({ maxLength: 2000 })),
      optionBy: Type.Optional(Type.Union([Type.Literal("label"), Type.Literal("value")])),
      checked: Type.Optional(Type.Boolean()),
      key: Type.Optional(Type.String({ maxLength: 40 })),
      submit: Type.Optional(Type.Boolean()),
      destination: Type.Optional(Type.String({ maxLength: 4000 })),
      loadState: Type.Optional(Type.Union([Type.Literal("load"), Type.Literal("domcontentloaded"), Type.Literal("networkidle")])),
      deltaY: Type.Optional(Type.Number()),
      settleMs: Type.Optional(Type.Integer()),
      maxScrolls: Type.Optional(Type.Integer()),
      ms: Type.Optional(Type.Integer()),
      timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 180 })),
    }),
    async execute(_id: string, params: any, signal: AbortSignal) {
      const operation = String(params.operation);
      if (!BROWSER_OPERATIONS.has(operation)) throw new Error("Capability denied: browser operation is not approved");
      if (!new Set(["read", "write"]).has(params.intent)) throw new Error("Capability denied: explicit read or write intent is required");
      if (READ_ONLY_OPERATIONS.has(operation) && params.intent !== "read") throw new Error(`${operation} is a read-only capability`);
      if (["fill", "type", "selectOption", "setChecked", "drag"].includes(operation) && params.intent !== "write") throw new Error(`${operation} requires write intent`);
      if (operation === "press" && !ALLOWED_KEYS.has(String(params.key))) throw new Error("Capability denied: keyboard key is not approved");
      if (operation === "press" && ["Backspace", "Delete"].includes(String(params.key)) && params.intent !== "write") throw new Error(`${params.key} requires write intent`);
      if (operation === "selectOption" && !["label", "value", undefined].includes(params.optionBy)) throw new Error("Capability denied: optionBy must be label or value");
      if (operation === "drag" && !params.destination) throw new Error("Capability denied: drag destination is required");
      if (params.intent === "write" && (!Array.isArray(params.scopeIds) || params.scopeIds.length === 0)) {
        throw new Error("Write blocked: confirmed Forge Intake scope IDs are required");
      }
      return withQueue("browser", async () => {
        await assertSnapshotConsumed();
        const input = browserParams(operation, params);
        const timeout = Math.max(1, Math.min(Number(params.timeoutSeconds ?? 90), 180));
        const result = await invokeBrowser(operation, input, signal, timeout);
        return toolText(await saveLargeSnapshot(result));
      });
    },
  });

  pi.registerTool({
    name: "cvent_snapshot_chunk",
    label: "Read complete snapshot chunk",
    description: "Read one transport chunk from a previously captured complete full-page Ego snapshot. Read every chunk before acting; this never triggers a smaller or targeted DOM read.",
    parameters: Type.Object({
      snapshotId: Type.String({ pattern: "^[0-9a-f-]{36}$" }),
      chunkIndex: Type.Integer({ minimum: 0, maximum: 1000 }),
    }),
    async execute(_id: string, params: any) {
      return withQueue("browser", async () => {
        const id = String(params.snapshotId);
        if (!/^[0-9a-f-]{36}$/.test(id)) throw new Error("Capability denied: invalid snapshot ID");
        const pending = await pendingSnapshot();
        if (!pending || pending.complete === true || pending.snapshotId !== id) throw new Error("Snapshot is not the active job-scoped transport");
        const runtime = await readJson(runtimePath, null);
        if (!runtime || pending.browserRuntimeId !== runtime.browserRuntimeId || pending.targetId !== runtime.targetBrowserIdentity?.targetId ||
            pending.workerSlot !== Number(requiredEnvironment("CVENT_WORKER_SLOT")) || pending.jobId !== requiredEnvironment("CVENT_JOB_ID") ||
            pending.workspaceId !== requiredEnvironment("CVENT_WORKSPACE_ID")) {
          throw new Error("Snapshot worker/browser/job identity mismatch");
        }
        const path = assertFixedJobPath(join(jobDir, "browser-snapshots", `${id}.txt`));
        const buffer = await readJobFile(path, MAX_SNAPSHOT_BYTES);
        if (buffer.length !== pending.bytes || hash(buffer) !== pending.sha256) throw new Error("Snapshot transport integrity check failed");
        const chunks = utf8Chunks(buffer.toString("utf8"), SNAPSHOT_CHUNK_BYTES);
        if (chunks.length !== pending.totalChunks) throw new Error("Snapshot chunk count changed");
        const index = Number(params.chunkIndex);
        if (index !== pending.nextChunk) throw new Error(`Snapshot chunks must be read exactly once in order; expected ${pending.nextChunk}`);
        const complete = index === chunks.length - 1;
        pending.nextChunk = index + 1;
        pending.complete = complete;
        await atomicJson(SNAPSHOT_PENDING, pending);
        return toolText({
          snapshotId: id, chunkIndex: index, totalChunks: chunks.length, complete,
          bytes: pending.bytes, sha256: pending.sha256, capturedAt: pending.capturedAt,
          browserRuntimeId: pending.browserRuntimeId, workerSlot: pending.workerSlot,
          targetId: pending.targetId, jobId: pending.jobId, workspaceId: pending.workspaceId,
          url: pending.url, title: pending.title, chunkText: chunks[index],
        });
      });
    },
  });

  pi.registerTool({
    name: "cvent_finish",
    label: "Finish Cvent job",
    description: "Write the final structured job report and end the agent turn. Use only after final QA or a genuine blocker. Cannot publish, mutate Cvent, select paths, or execute commands.",
    parameters: Type.Object({
      status: Type.String({ description: "DRAFT_COMPLETE, REVIEW_REQUIRED, or INCOMPLETE" }),
      unresolvedItems: Type.Array(Type.String({ maxLength: 3000 }), { maxItems: 200 }),
      realReads: Type.Array(Type.String({ maxLength: 3000 }), { maxItems: 500 }),
      realWrites: Type.Array(Type.String({ maxLength: 3000 }), { maxItems: 500 }),
      guardrails: Type.Object({
        published: Type.Integer({ minimum: 0 }),
        emailsSent: Type.Integer({ minimum: 0 }),
        deletes: Type.Integer({ minimum: 0 }),
        globalMutations: Type.Integer({ minimum: 0 }),
      }),
    }),
    async execute(_id: string, params: any) {
      if (!["DRAFT_COMPLETE", "REVIEW_REQUIRED", "INCOMPLETE"].includes(params.status)) throw new Error("Capability denied: invalid final status");
      return withQueue("job-files", async () => {
        const report = {
          status: params.status,
          unresolved_items: params.unresolvedItems,
          real_reads: params.realReads,
          real_writes: params.realWrites,
          guardrails: {
            published: params.guardrails.published,
            emails_sent: params.guardrails.emailsSent,
            deletes: params.guardrails.deletes,
            global_mutations: params.guardrails.globalMutations,
          },
          updated_at: new Date().toISOString(),
        };
        await atomicJson(join(jobDir, "final-report.json"), report);
        const state = await readJson(join(jobDir, "state.json"), {});
        if (params.status === "REVIEW_REQUIRED") state.status = "review_required";
        state.current_stage = "final_qa";
        state.current_action = params.status === "DRAFT_COMPLETE" ? "Draft build complete" : params.status.replaceAll("_", " ").toLowerCase();
        state.updated_at = new Date().toISOString();
        await atomicJson(join(jobDir, "state.json"), state);
        await appendActivity(`Final verdict: ${params.status}`);
        return { ...toolText({ ok: true, status: params.status }), terminate: true };
      });
    },
  });
}
