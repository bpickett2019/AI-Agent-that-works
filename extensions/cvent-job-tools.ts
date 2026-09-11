import { execFile } from "node:child_process";
import { randomUUID, createHash } from "node:crypto";
import { open, readFile, realpath, rename, mkdir, appendFile, lstat, unlink } from "node:fs/promises";
import { join, resolve } from "node:path";
import { Type } from "typebox";
import { retainJobContext, ValidatedRRCache, BrowserRecoveryBudget } from "./prewrite-orchestration.mjs";

const rrCache = new ValidatedRRCache();
const recoveryBudget = new BrowserRecoveryBudget();
let preparedRR: any = null;

const BROWSER_OPERATION_NAMES = [
  "probe", "recover", "authStatus", "authorizeTarget", "openAuthorizedEvent", "snapshotText", "screenshot", "readTarget", "sectionState", "controlInventory", "pageInfo", "scanEventList",
  "actions", "scroll", "click", "activate", "visualClick", "visualDoubleClick", "fill", "type", "typeText", "navigate", "wait", "hover", "selectOption", "setChecked", "press", "search", "selectText", "drag", "visualDrag", "uploadDiscountImport",
];
const PI_BROWSER_OPERATION_NAMES = BROWSER_OPERATION_NAMES;
const EGO_ACTION_OPERATIONS = ["pageInfo", "snapshotText", "screenshot", "readTarget", "sectionState", "controlInventory", "scroll", "click", "activate", "visualClick", "visualDoubleClick", "fill", "type", "typeText", "navigate", "wait", "hover", "selectOption", "setChecked", "press", "search", "selectText", "drag", "visualDrag", "uploadDiscountImport"] as const;
const TRUSTED_SECTION_PROCEDURES: Record<string, string> = {
  admission_items: "configureAdmissionItems", registration_types: "configureRegistrationTypes",
};
const BROWSER_OPERATIONS = new Set(BROWSER_OPERATION_NAMES);
const READ_ONLY_OPERATIONS = new Set([
  "probe", "recover", "authStatus", "authorizeTarget", "openAuthorizedEvent", "snapshotText", "screenshot", "readTarget", "sectionState", "controlInventory", "pageInfo", "scanEventList",
  "scroll", "navigate", "wait", "hover", "search", "selectText",]);
const ALLOWED_KEYS = new Set([
  "Enter", "Escape", "Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
  "Backspace", "Delete", "Home", "End", "PageUp", "PageDown", "Space",
]);
const DOMAIN_NAMES = [
  "event_settings", "site_designer", "registration_paths", "registration_types",
  "admission_items", "optional_items", "pricing", "discounts_vouchers",
  "questions", "sessions", "integrations", "communications", "badges_onsite", "associations", "final_qa",
] as const;
const DOMAINS = new Set<string>(DOMAIN_NAMES);
const JOB_STAGES = ["starting", "target_discovery", ...DOMAIN_NAMES] as const;
const literalUnion = (values: readonly string[]) => Type.Union(values.map((value) => Type.Literal(value)) as any);
const ARTIFACTS: Record<string, string> = {
  state: "state.json",
  auth_metadata: "auth-settings.json",
  target_lock: "authorized-target.json",
  activity: "activity.log",
  write_audit: "scope-write-audit.jsonl",
  browser_failure: "last-browser-failure-result.json",
  final_report: "final-report.json",
  domain_results: "domain-results.json",
  inspection_summary: "input.inspection-summary.json",
  browser_runtime: "browser-runtime.json",
  performance: "performance-summary.json",
};
const ALLOWED_TOOLS = new Set([
  "read", "bash",
  "cvent_prepare_rr", "cvent_expectations", "cvent_plan", "cvent_job_read",
  "cvent_job_update", "cvent_record_domain", "cvent_verify_domain", "cvent_browser", "cvent_section_state", "cvent_execute_section",
  "cvent_login_handoff", "cvent_snapshot_chunk", "cvent_finish",
]);
const MAX_TEXT_BYTES = 48 * 1024;
const SNAPSHOT_CHUNK_BYTES = 36 * 1024;
const MAX_CHILD_OUTPUT = 8 * 1024 * 1024;
const MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024;
const SNAPSHOT_PENDING = join(resolve(requiredEnvironment("CVENT_JOB_DIR")), "browser-snapshot-pending.json");
const WRITE_READBACK_PENDING = join(resolve(requiredEnvironment("CVENT_JOB_DIR")), "browser-write-readback-required.json");
const PERFORMANCE_EVENTS = join(resolve(requiredEnvironment("CVENT_JOB_DIR")), "performance-events.jsonl");
const ROUTE_CACHE = join(resolve(requiredEnvironment("CVENT_JOB_DIR")), "cvent-route-cache.json");
const queues = new Map<string, Promise<unknown>>();
const extensionStarted = performance.now();
let firstBrowserActionRecorded = false;
type TurnProgress = {
  turnIndex: number; section: string; browserOperations: number; browserActions: number; egoRounds: number;
  toolNames: string[]; requiredVerification: boolean; ambiguityResolved: boolean; humanOrSecurityBoundary: boolean;
  repeatedRead: boolean; modelDurationMs: number; toolCalls: Map<string, { name: string; args: any }>;
};
let activeTurnProgress: TurnProgress | null = null;

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

async function toolBrowserResult(value: any): Promise<any> {
  const base = toolText(value);
  const paths = new Set<string>();
  const visit = (item: any): void => {
    if (!item || typeof item !== "object") return;
    if (typeof item.screenshotPath === "string") paths.add(item.screenshotPath);
    for (const child of Object.values(item)) visit(child);
  };
  visit(value);
  for (const candidate of [...paths].slice(-2)) {
    const path = assertFixedJobPath(candidate);
    const image = await readJobFile(path, 12 * 1024 * 1024);
    base.content.push({ type: "image", data: image.toString("base64"), mimeType: "image/png" } as any);
  }
  return base;
}

function safeChildEnvironment(kind: "browser" | "prepare"): NodeJS.ProcessEnv {
  const names = ["PATH", "LANG", "LC_ALL", "TZ"];
  const environment: NodeJS.ProcessEnv = {};
  for (const name of names) if (process.env[name]) environment[name] = process.env[name];
  environment.CVENT_REPO_ROOT = repoRoot;
  environment.CVENT_JOB_DIR = jobDir;
  for (const name of [
    "CVENT_ENV", "CVENT_DATA_ROOT", "CVENT_JOB_ID", "CVENT_WORKSPACE_ID", "CVENT_WORKER_SLOT",
    "CVENT_STEEL_API_ORIGIN", "CVENT_CDP_ORIGIN", "CVENT_AUTHORIZED_EVENT_ID",
    "CVENT_AUTHORIZED_EVENT_NAME", "CVENT_AUTHORIZED_EVENT_KEY", "CVENT_AUTHORIZED_EVENT_CODE", "CVENT_WRITABLE_EVENT_STATUSES",
  ]) if (process.env[name]) environment[name] = process.env[name];
  if (kind === "browser") {
    environment.CVENT_LEASE_VALIDATE_URL = requiredEnvironment("CVENT_LEASE_VALIDATE_URL");
    environment.CVENT_LEASE_TOKEN = requiredEnvironment("CVENT_LEASE_TOKEN");
  }
  return environment;
}

function runFixed(executable: string, args: string[], kind: "browser" | "prepare", signal?: AbortSignal, timeout = 120000): Promise<{ stdout: string; stderr: string }> {
  const started = performance.now();
  return new Promise((resolvePromise, rejectPromise) => {
    execFile(executable, args, {
      cwd: repoRoot,
      env: safeChildEnvironment(kind),
      timeout,
      maxBuffer: MAX_CHILD_OUTPUT,
      signal,
      windowsHide: true,
    }, async (error, stdout, stderr) => {
      if (error) {
        const message = redact(`${error.message}\n${stderr || stdout}`);
        if (kind === "browser") {
          const operation = args[args.indexOf("--operation") + 1] || "unknown";
          recoveryBudget.failure(operation, message);
          try {
            await appendPerformance("browser_operation_failed", started, { operation, error: message, pid: process.pid });
            await appendActivity(`Browser operation ${operation} failed: ${message.slice(-900)}`);
            if (recoveryBudget.firstFailure) await atomicJson(join(jobDir, `first-browser-failure-${process.pid}.json`), recoveryBudget.firstFailure);
            if (recoveryBudget.terminalFailure) await atomicJson(join(jobDir, `controller-failure-${process.pid}.json`), recoveryBudget.terminalFailure);
          } catch { /* Preserve the actual helper error if telemetry fails. */ }
        }
        rejectPromise(new Error(message));
        return;
      }
      resolvePromise({ stdout: String(stdout), stderr: String(stderr) });
    });
  });
}

async function settleAuthenticatedProfile(initial: any, read: () => Promise<any>, pause: () => Promise<void>): Promise<any> {
  let auth = initial;
  // A restored, correctly bound profile can reach the SPA before rendering
  // finishes. Poll only reads, and never waive profile or account checks.
  for (let attempt = 0; attempt < 8 && !auth.authenticated && auth.persistedProfile === true &&
       auth.profileMatch === true && auth.accountContextMatch === true; attempt++) {
    await pause();
    auth = await read();
  }
  return auth;
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

async function appendPerformance(kind: string, startedMs: number, details: Record<string, unknown> = {}): Promise<void> {
  const target = await assertSafeArtifactTarget(PERFORMANCE_EVENTS);
  const payload = { timestamp: new Date().toISOString(), kind, durationMs: Math.max(0, Math.round((performance.now() - startedMs) * 10) / 10), ...details };
  await appendFile(target, `${JSON.stringify(payload)}\n`, { encoding: "utf8", mode: 0o600 });
}

async function appendActivity(message: string): Promise<void> {
  const safe = cleanText(message, 1200).replace(/[\r\n]+/g, " ");
  if (!safe) return;
  const target = await assertSafeArtifactTarget(join(jobDir, "activity.log"));
  await appendFile(target, `${new Date().toISOString()}  ${safe}\n`, { encoding: "utf8", mode: 0o600 });
}

async function updateBrowserProgress(action: string): Promise<void> {
  return withQueue("job-files", async () => {
    const path = join(jobDir, "state.json");
    const state = await readJson(path, {});
    state.current_action = cleanText(action, 1200);
    state.updated_at = new Date().toISOString();
    await atomicJson(path, state);
  });
}

function hash(buffer: Buffer): string {
  return createHash("sha256").update(buffer).digest("hex");
}

async function verifiedCompiledExpectations(): Promise<any> {
  const revision = async () => {
    await assertPrivateJobRoot();
    const files = await Promise.all(["input.xlsx", "expected-domains.json", "rr-validation.json", "configuration-plan.json"].map(async (name) => {
      const info = await lstat(join(jobDir, name));
      if (!info.isFile() || info.isSymbolicLink()) throw new Error("RR artifacts must be regular private job files");
      return [info.dev, info.ino, info.size, info.mtimeMs, info.ctimeMs];
    }));
    return JSON.stringify([files, requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY"), requiredEnvironment("CVENT_AUTHORIZED_EVENT_ID"), requiredEnvironment("CVENT_AUTHORIZED_EVENT_NAME")]);
  };
  return rrCache.get(revision, async () => {
  const input = await readJobFile(join(jobDir, "input.xlsx"), 25 * 1024 * 1024);
  const expected = await readJson(join(jobDir, "expected-domains.json"), null);
  const validation = await readJson(join(jobDir, "rr-validation.json"), null);
  const plan = await readJson(join(jobDir, "configuration-plan.json"), null);
  if (!expected || !validation || !plan) throw new Error("Write blocked: compile and independently validate the current RR with cvent_prepare_rr first");
  if (expected.rr?.sha256 !== hash(input) || expected.rr?.authority !== "uploaded_rr" ||
      expected.target?.eventKey !== requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY") ||
      expected.target?.eventId !== requiredEnvironment("CVENT_AUTHORIZED_EVENT_ID") ||
      expected.target?.name !== requiredEnvironment("CVENT_AUTHORIZED_EVENT_NAME") ||
      validation.rrSha256 !== expected.rr?.sha256 || plan.rrSha256 !== expected.rr?.sha256 ||
      plan.target?.eventId !== expected.target?.eventId) {
    throw new Error("Write blocked: compiled RR expectations are stale or belong to another target");
  }
  return expected;
  });
}

async function assertCompiledExpectations(): Promise<void> {
  await verifiedCompiledExpectations();
}

function parseMarker(stdout: string, marker: string): any {
  const line = stdout.split(/\r?\n/).reverse().find((item) => item.startsWith(marker));
  if (!line) throw new Error("Approved helper returned no structured result");
  const result = JSON.parse(line.slice(marker.length));
  if (!result?.ok) throw new Error(redact(result?.error || "Approved helper failed"));
  return result;
}

async function invokeBrowser(operation: string, params: Record<string, unknown>, signal?: AbortSignal, timeoutSeconds = 90): Promise<any> {
  const started = performance.now();
  if (!firstBrowserActionRecorded) {
    firstBrowserActionRecorded = true;
    await appendPerformance("first_browser_action", extensionStarted, { operation });
  }
  await readJobFile(runtimePath, 1024 * 1024);
  const trusted = Object.values(TRUSTED_SECTION_PROCEDURES).includes(operation);
  const coherent = operation === "actions" || operation === "script";
  const timeout = Math.max(1, Math.min(timeoutSeconds, operation === "recover" ? 30 : trusted || coherent ? 900 : 180));
  const boundedParams = { ...params, timeoutSeconds: timeout };
  const output = await runFixed(python, [
    join(repoRoot, "browser_tool.py"), "--runtime", runtimePath, "--tool", "ego",
    "--operation", operation, "--params", JSON.stringify(boundedParams),
  ], "browser", signal, (timeout + (operation === "recover" ? 45 : trusted || coherent ? 30 : 10)) * 1000);
  const result = parseMarker(output.stdout, "BROWSER_ROUTER_RESULT=");
  if (operation === "recover") recoveryBudget.recovered();
  const actionCount = operation === "script" ? Number(result.actionCount ?? 0) : coherent ? (params.steps as any[])?.length ?? 0 : 1;
  if (activeTurnProgress) {
    activeTurnProgress.browserOperations += 1;
    activeTurnProgress.browserActions += actionCount;
    if (coherent) activeTurnProgress.egoRounds += 1;
    if (!activeTurnProgress.section && typeof params.domain === "string") activeTurnProgress.section = params.domain;
  }
  await appendPerformance("browser_operation", started, { operation, section: activeTurnProgress?.section || params.domain || "", intent: params.intent, navigation: ["navigate", "openAuthorizedEvent"].includes(operation), snapshot: operation === "snapshotText", fullSnapshot: operation === "snapshotText", egoExecutionRound: coherent, actionCount, responseBytes: Buffer.byteLength(JSON.stringify(result)) });
  return result;
}

function fixedSectionMenuPath(domain: string): string[] {
  const paths: Record<string, string[]> = {
    optional_items: ["Registration", "Optional Items"], pricing: ["Registration", "Pricing"],
    integrations: ["Integrations"], communications: ["Email"], badges_onsite: ["OnArrival"],
    questions: ["Registration", "Registration Process"], registration_paths: ["Registration", "Registration Process"],
    site_designer: ["Registration", "Registration Overview"],
  };
  return paths[domain] ?? [];
}

function fixedSectionRoutes(): Record<string, string> {
  const key = encodeURIComponent(requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY"));
  return {
    event_settings: `https://app.cvent.com/Subscribers/Events2/Details/EventDetails/Index?evtstub=${key}`,
    registration_types: `https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypes/Index/View?evtstub=${key}`,
    admission_items: `https://app.cvent.com/Subscribers/Events2/AgendaAndFees/AdmissionItemGrid/Index/?evtstub=${key}`,
    discounts_vouchers: `https://app.cvent.com/Subscribers/Events2/AgendaAndFees/DiscountsGrid?evtstub=${key}`,
  };
}

async function rememberSectionRoute(url: string, explicitDomain?: string): Promise<void> {
  const state = await readJson(join(jobDir, "state.json"), {});
  const domain = String(explicitDomain ?? state.current_stage ?? "");
  if (!DOMAINS.has(domain)) return;
  const parsed = new URL(url);
  const eventKey = requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY").toLowerCase();
  if (!parsed.hostname.toLowerCase().endsWith("cvent.com") || !parsed.href.toLowerCase().includes(eventKey)) return;
  const routes = await readJson(ROUTE_CACHE, { schemaVersion: 1, routes: {} });
  routes.routes[domain] = { url: parsed.href, verifiedAt: new Date().toISOString(), browserRuntimeId: (await readJson(runtimePath, {})).browserRuntimeId };
  await atomicJson(ROUTE_CACHE, routes);
}

function desiredSectionRecords(domain: string, expected: any): any[] {
  const section = expected.domains?.[domain] ?? {};
  if (domain === "discounts_vouchers") return section.discounts ?? [];
  if (domain === "site_designer") return [...(section.footerLinks ?? []), ...(section.socialLinks ?? []), ...(section.countdownMessages ?? []), ...(section.inlineContentLinks ?? [])];
  if (domain === "event_settings") return Object.entries(section.fields ?? {}).map(([name, field]: any) => ({ matchReference: name.replace(/_/g, " "), fields: { [name]: field } }));
  return section.items ?? section.requirements ?? section.badgeRequirements ?? [];
}

function booleanValue(value: unknown): boolean {
  const normalized = cleanText(value, 40).toLowerCase();
  if (["y", "yes", "true", "active", "activate", "required", "1"].includes(normalized)) return true;
  if (["n", "no", "false", "inactive", "deactivate", "0"].includes(normalized)) return false;
  throw new Error("Verified RR boolean has an unsupported or missing value; refusing to guess");
}

function trustedProcedureRecords(domain: string, expected: any): any[] {
  const section = expected.domains?.[domain] ?? {};
  if (domain === "admission_items") {
    const registrationNames = new Map((expected.domains?.registration_types?.items ?? []).map((item: any) => [
      cleanText(item.fields?.registration_code?.value, 200), cleanText(item.fields?.registration_name?.value, 1000),
    ]));
    const knownRegistrationTypes = [...registrationNames.entries()].map(([code, name]) => ({ code, name }));
    return (section.items ?? []).map((item: any) => ({
      code: cleanText(item.fields?.admission_code?.value ?? item.matchReference, 200),
      name: cleanText(item.fields?.admission_name?.value, 1000),
      source: cleanText(item.fields?.admission_code?.source ?? item.fields?.admission_name?.source, 500),
      registrationTypes: [...new Set(item.registrationTypes ?? [])].map((code: any) => ({
        code: cleanText(code, 200), name: cleanText(registrationNames.get(cleanText(code, 200)) ?? code, 1000),
      })),
      knownRegistrationTypes,
    }));
  }
  if (domain === "registration_types") return (section.items ?? []).map((item: any) => {
    const activationDirective = cleanText(item.fields?.active?.value, 40).toUpperCase();
    if (!["ACTIVATE", "REQUIRED"].includes(activationDirective))
      throw new Error("Verified RR registration activation directive is unsupported; refusing to map it to a Cvent status");
    return {
      code: cleanText(item.fields?.registration_code?.value ?? item.matchReference, 200),
      name: cleanText(item.fields?.registration_name?.value, 1000),
      source: cleanText(item.fields?.registration_code?.source ?? item.fields?.registration_name?.source, 500),
      activationDirective,
      groupRegistration: item.fields?.group_registration?.value == null || cleanText(item.fields.group_registration.value, 40) === ""
        ? null : booleanValue(item.fields.group_registration.value),
      reprintFee: item.fields?.reprint_fee?.value == null ? null : Number(item.fields.reprint_fee.value),
    };
  });
  throw new Error(`No trusted procedure data projection exists for ${domain}`);
}

function verificationItemResults(domainItems: any[], matches: any[], exceptions: any[]): any[] {
  const ids = new Set(domainItems.map(item => item.itemId));
  const matched = new Map<string, any>();
  const held = new Map<string, any>();
  for (const item of matches) {
    if (!ids.has(item.itemId) || matched.has(item.itemId) || !item.cventEvidence?.length)
      throw new Error("Every explicit match needs unique domain identity and actual Cvent evidence");
    matched.set(item.itemId, item);
  }
  for (const item of exceptions) {
    if (!ids.has(item.itemId) || held.has(item.itemId) || matched.has(item.itemId))
      throw new Error("Verification outcomes must be unique and belong to this domain");
    held.set(item.itemId, item);
  }
  return domainItems.map(item => {
    const exception = held.get(item.itemId), match = matched.get(item.itemId);
    if (match && item.status !== "VERIFIED") throw new Error("Unverified RR evidence cannot be marked MATCH");
    return { itemId: item.itemId, rrStatus: item.status,
      status: exception?.status ?? (match ? "MATCH" : item.status === "VERIFIED" ? "NOT_CONFIGURED" : "AMBIGUOUS"),
      ...(match ? { cventEvidence: match.cventEvidence } : { reason: exception?.reason ?? "No explicit item-level Cvent readback was supplied" }) };
  });
}

async function assertSourcesVerified(domain: string, sources: string[]): Promise<void> {
  const validation = await readJson(join(jobDir, "rr-validation.json"), null);
  const verified = new Set((validation?.items ?? []).filter((item: any) => item.domain === domain && item.status === "VERIFIED")
    .map((item: any) => `${item.sourceEvidence.sheet}!${item.sourceEvidence.range}`));
  if (!sources.length || sources.some(source => !verified.has(source)))
    throw new Error("Item held: each write source must exactly match VERIFIED evidence in this domain; continue independent verified items");
}

async function assertDomainEvidenceVerified(domain: string): Promise<void> {
  const validation = await readJson(join(jobDir, "rr-validation.json"), null);
  const unsupported = (validation?.items ?? []).filter((item: any) => item.domain === domain && item.status !== "VERIFIED");
  if (unsupported.length) throw new Error(`Trusted ${domain} procedure blocked: ${unsupported.length} RR evidence items are not independently VERIFIED`);
}

async function replayHolds(domain: string): Promise<any[]> {
  const document = await readJson(join(jobDir, "replay-holds.json"), { holds: [] });
  if (document.eventKey && document.eventKey !== requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY"))
    throw new Error("Replay-hold evidence belongs to another event");
  return (document.holds ?? []).filter((hold: any) => hold?.domain === domain && hold?.automaticReplayPermitted === false && cleanText(hold?.identity, 500));
}

async function assertNoHeldReplay(domain: string, payload: any): Promise<void> {
  const serialized = JSON.stringify(payload);
  for (const hold of await replayHolds(domain)) {
    const identity = cleanText(hold.identity, 500);
    const pattern = new RegExp(`(^|[^A-Za-z0-9_-])${identity.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^A-Za-z0-9_-]|$)`, "i");
    if (pattern.test(serialized)) throw new Error(`MATCH_UNCERTAIN_HUMAN_REVIEW: automatic replay is blocked for held ${domain} identity ${identity}`);
  }
}

function compactSectionComparison(domain: string, expected: any, observed: any): any {
  const rows = observed.rows ?? [];
  const normalizedRows = rows.map((row: any) => ({ ...row, normalized: cleanText(row.text, 10000).toLowerCase().replace(/\s+/g, " ") }));
  const normalizedControls = (observed.controls ?? []).map((control: any) => ({ ...control, normalizedLabel: cleanText(control.label, 1000).toLowerCase().replace(/\s+/g, " ") }));
  const records = desiredSectionRecords(domain, expected);
  const comparisons = records.map((record: any, index: number) => {
    const fields = record.fields ?? {};
    const reference = record.matchReference ?? record.label ?? fields.code?.value ?? fields.registration_code?.value ?? fields.internal_name?.value ?? fields.name?.value ?? record.values?.A ?? record.values?.R ?? [record.registrationType, record.admissionItem].filter(Boolean).join(" / ");
    const desiredName = fields.registration_name?.value ?? fields.admission_name?.value ?? fields.name?.value;
    const needle = cleanText(reference, 1000).toLowerCase();
    const row = needle ? normalizedRows.find((item: any) => item.normalized.includes(needle)) : undefined;
    const control = needle ? normalizedControls.find((item: any) => item.normalizedLabel === needle || item.normalizedLabel.includes(needle)) : undefined;
    const onlyField: any = Object.values(fields)[0];
    const scalarDesired = Object.keys(fields).length === 1 && ![null, undefined, ""].includes(onlyField?.value) ? String(onlyField.value).toLowerCase().trim() : "";
    const controlMatches = control && scalarDesired ? String(control.value ?? "").toLowerCase().trim() === scalarDesired : Boolean(control);
    const nameMatches = !desiredName || (row && row.normalized.includes(cleanText(desiredName, 2000).toLowerCase().replace(/\s+/g, " ")));
    const found = row ?? control;
    return { index, reference, desiredName, status: !found ? "MISSING" : (row ? nameMatches : controlMatches) ? "PRESENT" : "DIFFERS", current: row ? { text: row.text, links: row.links } : control ? { label: control.label, value: control.value, selector: control.selector } : null };
  });
  const counts: Record<string, number> = { PRESENT: 0, DIFFERS: 0, MISSING: 0 };
  for (const item of comparisons) counts[item.status] += 1;
  const fullySummaryComparable = (item: any) => (item.desiredName || domain === "event_settings") && Object.keys(records[item.index]?.fields ?? {}).length <= 2;
  return { domain, counts,
    alreadyCorrect: comparisons.filter((item: any) => item.status === "PRESENT" && fullySummaryComparable(item)).map((item: any) => item.reference).slice(0, 1000),
    locatedNeedsDetailInspection: comparisons.filter((item: any) => item.status === "PRESENT" && !fullySummaryComparable(item)).map((item: any) => item.reference).slice(0, 1000),
    needsConfiguration: comparisons.filter((item: any) => item.status === "DIFFERS").slice(0, 200),
    missing: comparisons.filter((item: any) => item.status === "MISSING").slice(0, 200),
    observed: { url: observed.url, title: observed.title, rowCount: rows.length, controls: (observed.controls ?? []).slice(0, 200), headings: observed.headings, buttons: observed.buttons },
  };
}

function browserParams(operation: string, input: any): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (["authorizeTarget", "openAuthorizedEvent"].includes(operation)) {
    params.eventName = requiredEnvironment("CVENT_AUTHORIZED_EVENT_NAME");
    params.eventKey = requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY");
  }
  if (["scanEventList", "openAuthorizedEvent"].includes(operation)) {
    params.maxScrolls = Math.max(1, Math.min(Number(input.maxScrolls ?? 30), 60));
  }
  if (operation === "scanEventList") params.exactName = requiredEnvironment("CVENT_AUTHORIZED_EVENT_NAME");
  if (operation === "sectionState") params.domain = cleanText(input.domain, 80);
  if (["click", "activate", "fill", "type", "hover", "selectOption", "setChecked", "press", "search", "selectText", "drag", "wait", "uploadDiscountImport", "readTarget"].includes(operation) && input.target) {
    params.target = cleanText(input.target, 4000);
    if (input.targetContext) params.targetContext = cleanText(input.targetContext, 1000);
    if (Number.isInteger(input.targetIndex)) params.targetIndex = Math.max(0, Math.min(Number(input.targetIndex), 20));
  }
  if (["fill", "type", "typeText", "search"].includes(operation)) params.text = cleanText(input.text, 20000);
  if (["visualClick", "visualDoubleClick", "visualDrag"].includes(operation)) {
    params.x = Number(input.x); params.y = Number(input.y);
    if (operation === "visualDrag") { params.toX = Number(input.toX); params.toY = Number(input.toY); }
  }
  if (operation === "screenshot") params.fullPage = input.fullPage === true;
  if (operation === "selectOption") {
    params.option = cleanText(input.option, 2000);
    params.optionBy = input.optionBy === "value" ? "value" : "label";
  }
  if (operation === "setChecked") params.checked = Boolean(input.checked);
  if (operation === "press") params.key = cleanText(input.key, 40);
  if (operation === "search") params.submit = input.submit !== false;
  if (operation === "drag") params.destination = cleanText(input.destination, 4000);
  if (operation === "uploadDiscountImport") params.artifact = "discount-import.xlsx";
  if (operation === "navigate") {
    params.url = cleanText(input.url, 8000);
    params.waitUntil = ["load", "domcontentloaded", "networkidle"].includes(input.loadState) ? input.loadState : "domcontentloaded";
  }
  if (operation === "scroll") {
    params.deltaY = Math.max(-10000, Math.min(Number(input.deltaY ?? 700), 10000));
    params.settleMs = Math.max(100, Math.min(Number(input.settleMs ?? 500), 5000));
  }
  if (operation === "wait") {
    params.ms = Math.max(50, Math.min(Number(input.ms ?? 1000), 30000));
    if (["load", "domcontentloaded", "networkidle"].includes(input.loadState)) params.loadState = input.loadState;
  }
  params.intent = input.intent;
  if (input.label) params.label = cleanText(input.label, 120);
  if (input.rrSource) params.rrSource = cleanText(input.rrSource, 500);
  return params;
}

function validateGeneralBrowserAction(operation: string, params: any): void {
  if (!BROWSER_OPERATIONS.has(operation)) throw new Error("Capability denied: browser operation is not approved");
  if (!new Set(["read", "write"]).has(params.intent)) throw new Error("Capability denied: explicit read or write intent is required");
  if (READ_ONLY_OPERATIONS.has(operation) && params.intent !== "read") throw new Error(`${operation} is a read-only capability`);
  if (["fill", "type", "typeText", "selectOption", "setChecked", "drag", "visualDrag", "uploadDiscountImport"].includes(operation) && params.intent !== "write") throw new Error(`${operation} requires write intent`);
  if (operation === "press" && !ALLOWED_KEYS.has(String(params.key))) throw new Error("Capability denied: keyboard key is not approved");
  if (operation === "press" && ["Backspace", "Delete"].includes(String(params.key)) && params.intent !== "write") throw new Error(`${params.key} requires write intent`);
  if (operation === "selectOption" && !["label", "value", undefined].includes(params.optionBy)) throw new Error("Capability denied: optionBy must be label or value");
  if (operation === "drag" && !params.destination) throw new Error("Capability denied: drag destination is required");
  if (["visualClick", "visualDoubleClick", "visualDrag"].includes(operation)) {
    for (const coordinate of operation === "visualDrag" ? [params.x, params.y, params.toX, params.toY] : [params.x, params.y]) {
      if (!Number.isFinite(coordinate) || coordinate < 0 || coordinate > 10000) throw new Error("Capability denied: visual action coordinates are invalid");
    }
  }
  if (params.intent === "write" && !cleanText(params.rrSource, 500)) throw new Error("Dynamic Cvent writes require verified RR source evidence");
}

function validateActionRound(commitMode: string, steps: any[]): void {
  let unverifiedWrite = false;
  let saveObserved = false;
  const readbacks = new Set(["readTarget", "sectionState", "controlInventory", "snapshotText", "screenshot"]);
  for (const step of steps) {
    validateGeneralBrowserAction(String(step.operation), step);
    if (step.operation === "navigate" && unverifiedWrite) throw new Error("Verify the saved configuration group before navigating within an Ego action round");
    if (step.intent === "write") {
      unverifiedWrite = true;
      if (["click", "activate", "press", "visualClick"].includes(step.operation) && /save/i.test(String(step.target ?? step.key ?? step.label ?? ""))) saveObserved = true;
    } else if (unverifiedWrite && readbacks.has(step.operation) && (commitMode === "autosave" || saveObserved)) {
      unverifiedWrite = false;
      saveObserved = false;
    }
  }
  if (unverifiedWrite) throw new Error("Every saved/autosaved configuration group needs meaningful readback in the same Ego action round");
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

async function pendingWriteReadback(): Promise<any> {
  return readJson(WRITE_READBACK_PENDING, null);
}

async function clearWriteReadback(): Promise<void> {
  try {
    const info = await lstat(WRITE_READBACK_PENDING);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error("Write readback marker is not a regular job artifact");
    await unlink(WRITE_READBACK_PENDING);
  } catch (error: any) {
    if (error?.code !== "ENOENT") throw error;
  }
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
const browserActionFields = {
  intent: Type.Union([Type.Literal("read"), Type.Literal("write")]),
  target: Type.Optional(Type.String({ maxLength: 4000, description: 'An exact target copied from the latest Ego snapshot (`@123`, `ref=123`, or `[ref=123]`), an exact role:<role>[name="<accessible name>"], or stable CSS returned by compact section state. Prefer fresh snapshot refs. Never invent selector syntax.' })),
  targetContext: Type.Optional(Type.String({ maxLength: 1000 })),
  targetIndex: Type.Optional(Type.Integer({ minimum: 0, maximum: 20 })),
  text: Type.Optional(Type.String({ maxLength: 20000 })),
  option: Type.Optional(Type.String({ maxLength: 2000 })),
  optionBy: Type.Optional(Type.Union([Type.Literal("label"), Type.Literal("value")])),
  checked: Type.Optional(Type.Boolean()),
  key: Type.Optional(literalUnion([...ALLOWED_KEYS])),
  destination: Type.Optional(Type.String({ maxLength: 4000 })),
  url: Type.Optional(Type.String({ maxLength: 8000 })),
  loadState: Type.Optional(Type.Union([Type.Literal("load"), Type.Literal("domcontentloaded"), Type.Literal("networkidle")])),
  deltaY: Type.Optional(Type.Integer({ minimum: -10000, maximum: 10000 })),
  settleMs: Type.Optional(Type.Integer({ minimum: 100, maximum: 5000 })),
  ms: Type.Optional(Type.Integer({ minimum: 50, maximum: 30000 })),
  domain: Type.Optional(literalUnion(DOMAIN_NAMES)),
  rrSource: Type.Optional(Type.String({ maxLength: 500 })),
  x: Type.Optional(Type.Number({ minimum: 0, maximum: 10000 })),
  y: Type.Optional(Type.Number({ minimum: 0, maximum: 10000 })),
  toX: Type.Optional(Type.Number({ minimum: 0, maximum: 10000 })),
  toY: Type.Optional(Type.Number({ minimum: 0, maximum: 10000 })),
  fullPage: Type.Optional(Type.Boolean()),
  label: Type.Optional(Type.String({ maxLength: 120 })),

  timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 300 })),
};
const egoActionSchema = Type.Object({ operation: literalUnion(EGO_ACTION_OPERATIONS), ...browserActionFields });

export default function cventJobTools(pi: any) {
  let turnStarted = 0;
  let firstTokenRecorded = false;
  let currentSection = "";
  const sectionTurns = new Map<string, number>();
  const deliveredPlanReads = new Set<string>();
  const safeMetric = async (kind: string, started: number, details: Record<string, unknown> = {}) => {
    try { await appendPerformance(kind, started, details); } catch { /* metrics never block configuration */ }
  };
  const sectionFrom = (toolName: string, args: any): string => {
    const candidate = toolName === "cvent_plan" || toolName === "cvent_expectations" ? args?.section : args?.domain ?? args?.stage;
    return DOMAINS.has(String(candidate ?? "")) ? String(candidate) : "";
  };
  const planDeliveryKey = (args: any): string =>
    `${String(args?.section ?? "")}:${Number(args?.offset ?? 0)}:${Number(args?.limit ?? 0)}`;
  pi.on("session_start", async () => {
    pi.setActiveTools([...ALLOWED_TOOLS]);
    await safeMetric("pi_session_start", performance.now(), { pid: process.pid });
  });
  pi.on("context", async (event: any) => {
    const messages = event.messages ?? [];
    const filtered = retainJobContext(messages);
    if (filtered === messages) return undefined;
    await safeMetric("context_pruned", performance.now(), { originalMessages: messages.length, retainedMessages: filtered.length });
    return { messages: filtered };
  });
  pi.on("turn_start", (event: any) => {
    turnStarted = performance.now(); firstTokenRecorded = false;
    activeTurnProgress = { turnIndex: Number(event.turnIndex ?? 0), section: currentSection, browserOperations: 0, browserActions: 0, egoRounds: 0,
      toolNames: [], requiredVerification: false, ambiguityResolved: false, humanOrSecurityBoundary: false,
      repeatedRead: false, modelDurationMs: 0, toolCalls: new Map() };
  });
  pi.on("message_update", async (event: any) => {
    if (!firstTokenRecorded && event.message?.role === "assistant") {
      firstTokenRecorded = true;
      await safeMetric("anthropic_first_token", turnStarted || performance.now());
    }
  });
  pi.on("message_end", async (event: any) => {
    if (event.message?.role !== "assistant") return;
    const usage = event.message.usage ?? {};
    const calls = (event.message.content ?? []).filter((item: any) => item.type === "toolCall");
    for (const call of calls) {
      const section = sectionFrom(String(call.name), call.arguments);
      if (section) { currentSection = section; if (activeTurnProgress) activeTurnProgress.section = section; }
    }
    if (activeTurnProgress) {
      activeTurnProgress.toolNames = calls.map((call: any) => String(call.name));
      activeTurnProgress.modelDurationMs = Math.max(0, Math.round((performance.now() - (turnStarted || performance.now())) * 10) / 10);
    }
    await safeMetric("anthropic_response", turnStarted || performance.now(), {
      turnIndex: activeTurnProgress?.turnIndex ?? 0, section: activeTurnProgress?.section || "",
      inputTokens: usage.input ?? 0, outputTokens: usage.output ?? 0,
      cacheReadTokens: usage.cacheRead ?? 0, cacheWriteTokens: usage.cacheWrite ?? 0,
      totalTokens: usage.totalTokens ?? 0,
    });
  });
  pi.on("tool_execution_start", (event: any) => {
    if (!activeTurnProgress) return;
    activeTurnProgress.toolCalls.set(String(event.toolCallId), { name: String(event.toolName), args: event.args ?? {} });
    const section = sectionFrom(String(event.toolName), event.args);
    if (section) { activeTurnProgress.section = section; currentSection = section; }
    if (["cvent_plan", "cvent_expectations"].includes(String(event.toolName))) {
      const key = planDeliveryKey(event.args);
      if (deliveredPlanReads.has(key)) activeTurnProgress.repeatedRead = true;
    }
  });
  pi.on("tool_execution_end", (event: any) => {
    if (!activeTurnProgress || event.isError) return;
    const call = activeTurnProgress.toolCalls.get(String(event.toolCallId));
    const name = String(call?.name ?? event.toolName ?? "");
    if (["cvent_plan", "cvent_expectations"].includes(name)) {
      const args = call?.args ?? {};
      const key = planDeliveryKey(args);
      if (!deliveredPlanReads.has(key)) activeTurnProgress.ambiguityResolved = true;
      deliveredPlanReads.add(key);
    }
    if (name === "cvent_snapshot_chunk") activeTurnProgress.ambiguityResolved = true;
    if (["cvent_prepare_rr", "cvent_verify_domain", "cvent_finish"].includes(name)) activeTurnProgress.requiredVerification = true;
    if (name === "cvent_login_handoff") activeTurnProgress.humanOrSecurityBoundary = true;
  });
  pi.on("turn_end", async () => {
    const progress = activeTurnProgress;
    if (!progress) return;
    const zeroProgress = progress.browserOperations === 0 && !progress.ambiguityResolved && !progress.requiredVerification && !progress.humanOrSecurityBoundary;
    let sectionTurn = 0;
    if (DOMAINS.has(progress.section)) {
      sectionTurn = (sectionTurns.get(progress.section) ?? 0) + 1;
      sectionTurns.set(progress.section, sectionTurn);
    }
    const details = { turnIndex: progress.turnIndex, section: progress.section, sectionTurn, browserOperations: progress.browserOperations,
      browserActions: progress.browserActions, egoRounds: progress.egoRounds, toolNames: progress.toolNames,
      modelDurationMs: progress.modelDurationMs, repeatedRead: progress.repeatedRead, zeroProgress };
    await safeMetric("model_response_progress", turnStarted || performance.now(), details);
    if (zeroProgress) await safeMetric("MODEL_RESPONSE_WITH_ZERO_PROGRESS", performance.now(), details);
    if (["event_settings", "registration_types", "admission_items", "pricing"].includes(progress.section) && sectionTurn > 3)
      await safeMetric("MODEL_CALL_BUDGET_EXCEEDED", performance.now(), { section: progress.section, sectionTurn, targetMaximum: 3 });
    activeTurnProgress = null;
  });
  pi.on("before_agent_start", async (event: any) => {
    pi.setActiveTools([...ALLOWED_TOOLS]);
    const active = pi.getActiveTools();
    const required = ["read", "bash", "cvent_prepare_rr", "cvent_plan", "cvent_browser", "cvent_finish"];
    const missing = required.filter(name => !active.includes(name));
    await atomicJson(join(jobDir, "pi-capabilities.json"), { activeTools: active, missing, pid: process.pid });
    await atomicJson(join(jobDir, "pi-system-prompt.json"), { systemPrompt: event.systemPrompt });
    if (missing.length) throw new Error(`PI_CAPABILITY_MISMATCH: ${missing.join(", ")}`);
  });
  pi.on("tool_call", async (event: any) => {
    if (!ALLOWED_TOOLS.has(event.toolName)) {
      return { block: true, reason: "Capability denied: this production agent has no shell or general filesystem tools" };
    }
    // Reporting a real job-wide blocker must remain available even when the
    // browser circuit breaker is open. It cannot perform browser mutations.
    if (event.toolName === "cvent_finish") return undefined;
    const decision = recoveryBudget.allow(event.toolName, event.input);
    if (!decision.allowed) {
      if (decision.terminal) await atomicJson(join(jobDir, `controller-failure-${process.pid}.json`), recoveryBudget.terminalFailure);
      return { block: true, terminate: decision.terminal, reason: decision.terminal
        ? "Browser runtime failed; stopping without further actions. The controller has the exact error. Do not reload the RR or reset the profile."
        : "Browser runtime unavailable, not an RR or login failure. Only one cvent_browser recover (intent read) is permitted; do not reread plans or request SSO." };
    }
    if (decision.recovery || (event.toolName === "cvent_browser" && event.input?.operation === "recover")) event.input.timeoutSeconds = 30;
    return undefined;
  });

  pi.registerTool({
    name: "read", label: "Read verified job input or Ego skill",
    description: "Read the Ego skill or this job's verified RR plan/evidence. Supports offset/limit, not secrets or other jobs.",
    promptSnippet: "Read Ego skill and verified job files",
    parameters: Type.Object({ path: Type.String(), offset: Type.Optional(Type.Integer({ minimum: 1 })), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 2000 })) }),
    async execute(_id: string, params: any) {
      const target = resolve(jobDir, params.path);
      const skill = join(repoRoot, "skills/ego-browser/SKILL.md");
      const allowed = ["configuration-plan.json", "rr-validation.json", "expected-domains.json", "input.inspection.json", "job-prompt.md"];
      if (target !== skill && !allowed.some(name => target === join(jobDir, name))) throw new Error("Read is limited to the Ego skill and verified job input");
      const text = target === skill ? await readFile(skill, "utf8") : (await readJobFile(target, 25 * 1024 * 1024)).toString("utf8");
      const lines = text.split("\n"), start = (params.offset ?? 1) - 1;
      const result = toolText(lines.slice(start, start + (params.limit ?? 500)).join("\n"));
      result.details = { totalLines: lines.length, offset: start + 1 };
      return result;
    },
  });

  pi.registerTool({
    name: "bash", label: "Ego native browser round",
    description: "Run ego-browser nodejs heredocs using the loaded Ego skill. Browser-only; no general shell. One script can observe, navigate, edit multiple controls, Save and verify. Header: // cvent: {\"domain\":\"event_settings\",\"commitMode\":\"read_only\"}. Use save/autosave and exact rrSources from the verified plan for configuration.",
    promptSnippet: "Execute coherent Ego browser heredocs",
    parameters: Type.Object({ command: Type.String({ maxLength: 50000 }), timeout: Type.Optional(Type.Integer({ minimum: 1, maximum: 780 })) }),
    async execute(_id: string, params: any, signal: AbortSignal) {
      const match = params.command.trim().match(/^ego-browser(?: nodejs)? <<'([A-Za-z][A-Za-z0-9_]*)'\r?\n([\s\S]*)\r?\n\1$/);
      if (!match) throw new Error("Use only ego-browser <<'EOF' ... EOF as documented by the vendored Ego skill");
      const header = match[2].match(/^\s*\/\/ cvent: (\{[^\n]+\})/);
      // Unmodified upstream Ego examples are read-only by default. A concise
      // Cvent header is needed only to grant RR-attributed write authority.
      const meta = header ? JSON.parse(header[1]) : { domain: currentSection || "event_settings", commitMode: "read_only", rrSources: [] };
      if (activeTurnProgress && DOMAINS.has(meta.domain)) { activeTurnProgress.section = meta.domain; currentSection = meta.domain; }
      if (!DOMAINS.has(meta.domain) || !["save", "autosave", "read_only"].includes(meta.commitMode)) throw new Error("Invalid Ego round domain/commitMode");
      return withQueue("browser", async () => {
        await assertSnapshotConsumed();
        const write = meta.commitMode !== "read_only";
        await assertCompiledExpectations();
        if (write) {
          await assertSourcesVerified(meta.domain, meta.rrSources ?? []);
          await assertNoHeldReplay(meta.domain, { sources: meta.rrSources, script: match[2] });
        }
        await appendActivity(`${write ? "Configuring" : "Inspecting"} ${meta.domain} with native Ego`);
        const result = await invokeBrowser("script", { intent: write ? "write" : "read", domain: meta.domain,
          commitMode: meta.commitMode, rrSources: meta.rrSources ?? [], script: match[2] }, signal, params.timeout ?? 180);
        await appendPerformance("ego_execution_round", performance.now(), { domain: meta.domain,
          actionCount: result.actionCount, writeCount: result.writesAttempted, saves: result.saves, readbacks: result.readbacks });
        await appendActivity(`Ego ${meta.domain}: ${result.actionCount} actions, ${result.writesAttempted} writes, ${result.saves} saves, ${result.readbacks} readbacks`);
        return toolBrowserResult(result);
      });
    },
  });

  pi.registerTool({
    name: "cvent_prepare_rr",
    label: "Prepare RR",
    description: "Inspect the uploaded RR and compile its event-configuration requirements using fixed server helpers. Takes no paths or commands.",
    parameters: Type.Object({}),
    async execute(_id: string, _params: unknown, signal: AbortSignal) {
      return withQueue("job-files", async () => {
        try {
          const existing = await verifiedCompiledExpectations();
          const alreadyPrepared = preparedRR === existing;
          if (alreadyPrepared) return toolText({ ok: true, reusedPreflight: true, alreadyPrepared: true, instruction: "The validated RR plan is still in context. Continue at the browser boundary; do not repeat setup." });
          const plan = await readJson(join(jobDir, "configuration-plan.json"), null);
          const validation = await readJson(join(jobDir, "rr-validation.json"), null);
          const firstDomain = plan.mission?.[0]?.domain;
          await appendActivity(`RR plan ready: ${existing.counts?.applicableFields ?? 0} RR evidence fields; server preflight reused`);
          preparedRR = existing;
          return toolText({ ok: true, reusedPreflight: true, counts: existing.counts, target: plan.target,
            mission: plan.mission.map((section: any) => ({ order: section.order, domain: section.domain, verifiedItems: section.verifiedItemIds?.length ?? 0, heldItems: section.heldItems })),
            firstDomain, items: validation.items.filter((item: any) => item.domain === firstDomain),
            instruction: "Setup and the first domain plan are complete. Check authentication and open the exact authorized event next. Do not reread summary or mission." });
        } catch {
          // Missing or stale artifacts are rebuilt only by the same fixed approved helpers below.
        }
        await assertSafeArtifactTarget(join(jobDir, "input.inspection.json"));
        await assertSafeArtifactTarget(join(jobDir, "input.inspection-summary.json"));
        await assertSafeArtifactTarget(join(jobDir, "expected-domains.json"));
        await assertSafeArtifactTarget(join(jobDir, "rr-validation.json"));
        await assertSafeArtifactTarget(join(jobDir, "configuration-plan.json"));
        await runFixed(python, [join(repoRoot, "inspect_rr.py"), join(jobDir, "input.xlsx"), join(jobDir, "input.inspection.json")], "prepare", signal, 180000);
        const compiled = await runFixed(python, [join(repoRoot, "rr_compiler.py")], "prepare", signal, 180000);
        const validated = await runFixed(python, [join(repoRoot, "rr_validator.py")], "prepare", signal, 180000);
        const result = JSON.parse(compiled.stdout);
        result.validation = JSON.parse(validated.stdout).counts;
        await appendActivity(`RR extracted and independently validated: ${result.counts?.applicableFields ?? 0} writable fields; ${result.validation?.AMBIGUOUS ?? 0} ambiguous`);
        return toolText(result);
      });
    },
  });

  pi.registerTool({
    name: "cvent_expectations",
    label: "Read RR expectations",
    description: "Read normalized requirements from the uploaded RR for one configuration domain, summary, protected actions, or capability gaps. Large record arrays are paged.",
    parameters: Type.Object({
      section: Type.String({ description: "summary, protected, gaps, or a configuration domain name" }),
      offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000 })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 25 })),
    }),
    async execute(_id: string, params: any) {
      const expected = await readJson(join(jobDir, "expected-domains.json"), null);
      if (!expected) throw new Error("Run cvent_prepare_rr first");
      const section = String(params.section);
      const deliveryKey = planDeliveryKey(params);
      if (deliveredPlanReads.has(deliveryKey)) return toolText({ ok: true, alreadyDelivered: true, section, instruction: "Use the validated RR data already present in the live model context; do not reread it through another wrapper." });
      let value: any;
      if (section === "summary") value = { rr: expected.rr, target: expected.target, counts: expected.counts };
      else if (section === "protected") value = expected.protected;
      else if (section === "gaps") value = expected.capabilityGaps;
      else if (DOMAINS.has(section)) value = expected.domains?.[section];
      else throw new Error("Capability denied: unknown expectation section");
      return toolText(pageArrays(value, params.offset ?? 0, params.limit ?? 10));
    },
  });

  pi.registerTool({
    name: "cvent_plan",
    label: "Read validated configuration plan",
    description: "Read the complete pre-Cvent mission summary or one ordered section with RR source evidence and independent VERIFIED/AMBIGUOUS/NOT_SUPPORTED_BY_RR status.",
    parameters: Type.Object({
      section: Type.String({ description: "summary, mission, or a configuration domain name" }),
      offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 20000 })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
    }),
    async execute(_id: string, params: any) {
      await verifiedCompiledExpectations();
      const plan = await readJson(join(jobDir, "configuration-plan.json"), null);
      const validation = await readJson(join(jobDir, "rr-validation.json"), null);
      const section = String(params.section);
      const deliveryKey = planDeliveryKey(params);
      if (deliveredPlanReads.has(deliveryKey)) return toolText({ ok: true, alreadyDelivered: true, section, instruction: "Use the validated RR data already present in the live model context; do not reread it through another wrapper." });
      if (section === "summary") return toolText({ counts: validation.counts, target: plan.target, executionRule: plan.executionRule });
      if (section === "mission") return toolText(plan.mission);
      if (!DOMAINS.has(section)) throw new Error("Capability denied: unknown plan section");
      const items = validation.items.filter((item: any) => item.domain === section);
      return toolText(pageArrays(items, params.offset ?? 0, params.limit ?? 25));
    },
  });

  pi.registerTool({
    name: "cvent_job_read",
    label: "Read job artifact",
    description: "Read one fixed safe job artifact: state, auth_metadata, target_lock, activity, write_audit, browser_failure (partial dispatch evidence), final_report, domain_results, inspection_summary, or browser_runtime. No path input is accepted.",
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
      status: Type.Optional(literalUnion(["running", "login_required", "review_required"])),
      stage: Type.Optional(literalUnion(JOB_STAGES)),
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
        if (params.stage && !DOMAINS.has(params.stage) && !["starting", "target_discovery"].includes(params.stage)) {
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
        await appendPerformance("stage_marker", performance.now(), { stage: state.current_stage, action: state.current_action, status: state.status });
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
      domain: literalUnion(DOMAIN_NAMES),
      status: literalUnion(["in_progress", "completed", "review_required", "incomplete"]),
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
        await appendPerformance("domain_result", performance.now(), { domain: params.domain, status: params.status });
        return toolText({ ok: true, domain: params.domain, status: params.status });
      });
    },
  });

  pi.registerTool({
    name: "cvent_verify_domain",
    label: "Record RR versus Cvent verification",
    description: "Account for every RR item after fresh Cvent readback. Supply explicit item-level matches with evidence; omitted items remain NOT_CONFIGURED, never implicitly MATCH.",
    parameters: Type.Object({
      domain: literalUnion(DOMAIN_NAMES),
      cventEvidence: Type.Array(Type.String({ maxLength: 3000 }), { minItems: 1, maxItems: 100 }),
      matches: Type.Optional(Type.Array(Type.Object({
        itemId: Type.String({ pattern: "^[0-9a-f]{20}$" }),
        cventEvidence: Type.Array(Type.String({ minLength: 1, maxLength: 3000 }), { minItems: 1, maxItems: 10 }),
      }), { maxItems: 8000 })),
      exceptions: Type.Array(Type.Object({
        itemId: Type.String({ pattern: "^[0-9a-f]{20}$" }),
        status: Type.Union([Type.Literal("NOT_CONFIGURED"), Type.Literal("AMBIGUOUS"), Type.Literal("PROHIBITED")]),
        reason: Type.String({ maxLength: 2000 }),
      }), { maxItems: 500 }),
    }),
    async execute(_id: string, params: any) {
      if (!DOMAINS.has(params.domain)) throw new Error("Capability denied: unknown domain");
      return withQueue("job-files", async () => {
        const validation = await readJson(join(jobDir, "rr-validation.json"), null);
        if (!validation) throw new Error("Run cvent_prepare_rr first");
        const domainItems = validation.items.filter((item: any) => item.domain === params.domain);
        const items = verificationItemResults(domainItems, params.matches ?? [], params.exceptions);
        const document = await readJson(join(jobDir, "final-verification.json"), { schemaVersion: 1, domains: {} });
        document.domains[params.domain] = {
          verifiedAt: new Date().toISOString(), cventEvidence: params.cventEvidence,
          items,
        };
        document.updatedAt = new Date().toISOString();
        await atomicJson(join(jobDir, "final-verification.json"), document);
        const counts: Record<string, number> = {};
        for (const item of document.domains[params.domain].items) counts[item.status] = (counts[item.status] ?? 0) + 1;
        return toolText({ ok: true, domain: params.domain, counts });
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
        let modernPageOutsideAuthorizedEvent = false;
        try {
          const parsed = new URL(pageUrl);
          const key = (parsed.searchParams.get("evtstub") ?? parsed.searchParams.get("eventid") ?? parsed.searchParams.get("event") ?? "").toLowerCase();
          modernPageOutsideAuthorizedEvent = host === "events.app.cvent.com" && key !== requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY").toLowerCase();
        } catch { /* fixed navigation below */ }
        if (!pageUrl || pageUrl === "about:blank" || !recognizedLoginHost || modernPageOutsideAuthorizedEvent) {
          await invokeBrowser("navigate", { intent: "read", url: "https://app.cvent.com/subscribers/default.aspx" }, signal, 60);
          pageResult = await invokeBrowser("pageInfo", { intent: "read" }, signal, 45);
          pageUrl = String(pageResult?.page?.url ?? "");
          pageTitle = String(pageResult?.page?.title ?? "");
          try { host = new URL(pageUrl).hostname.toLowerCase(); } catch { host = ""; }
        }
        const auth = await settleAuthenticatedProfile(
          await invokeBrowser("authStatus", { intent: "read" }, signal, 45),
          () => invokeBrowser("authStatus", { intent: "read" }, signal, 45),
          () => new Promise<void>(resolvePromise => setTimeout(resolvePromise, 500)),
        );
        if (auth.authenticated === true && auth.workerSlot === Number(requiredEnvironment("CVENT_WORKER_SLOT"))) {
          await appendActivity("Cvent login already active; verified this worker's isolated persisted profile");
          return toolText({ ok: true, loginRequired: false, persistedProfileReused: true,
            instruction: "Cvent login already active in this worker's isolated profile; fresh-read a complete snapshot and continue." });
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
        state.current_action = "Complete Cvent SSO/MFA in the browser, then return control to the agent";
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
        const humanHandoffStarted = performance.now();

        const deadline = Date.now() + 60 * 60 * 1000;
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
            await appendActivity("User returned browser control; authenticated slot profile verified and persisted automatically");
            await safeMetric("human_handoff", humanHandoffStarted, { boundary: "cvent_sso_mfa", completed: true });
            return toolText({ ok: true, resumed: true, profilePersisted: true,
              instruction: "Forge verified and persisted this slot's Cvent login. Fresh-read pageInfo and a complete snapshot before continuing." });
          }
          if (current.ownership === "NONE") throw new Error("Browser return was blocked; human review is required");
        }
        await safeMetric("human_handoff", humanHandoffStarted, { boundary: "cvent_sso_mfa", completed: false });
        throw new Error("Cvent login handoff timed out after 60 minutes");
      });
    },
  });

  pi.registerTool({
    name: "cvent_section_state",
    label: "Read complete Cvent section state",
    description: "Open a cached or proven exact-event section route once, collect compact structured table/form state for all RR records, and return only aggregate matches plus exceptions. Use before any per-record discovery.",
    parameters: Type.Object({ domain: literalUnion(DOMAIN_NAMES) }),
    async execute(_id: string, params: any, signal: AbortSignal) {
      const domain = String(params.domain);
      await assertSnapshotConsumed();
      if (await pendingWriteReadback()) throw new Error("Complete pending write readback before changing sections");
      const expected = await verifiedCompiledExpectations();
      const runtime = await readJson(runtimePath, {});
      const cache = await readJson(ROUTE_CACHE, { routes: {} });
      const cached = cache.routes?.[domain];
      const route = cached?.browserRuntimeId === runtime.browserRuntimeId ? cached.url : fixedSectionRoutes()[domain];
      const menuPath = fixedSectionMenuPath(domain);
      if (!route && !menuPath.length) return toolText({ ok: false, domain, exception: "NO_PROVEN_ROUTE", instruction: "Use Pi discovery once; successful exact-event navigation will be cached for this job." });
      return withQueue("browser", async () => {
        const base = route ?? fixedSectionRoutes().event_settings.replace("/Details/EventDetails/Index", "/Overview/Overview/Index/View");
        const navigation = await invokeBrowser("navigate", browserParams("navigate", { intent: "read", url: base, loadState: "domcontentloaded" }), signal, 120);
        for (const label of menuPath) {
          await invokeBrowser("click", browserParams("click", { intent: "read", target: `role:menuitem[name="${label}"]` }), signal, 60);
          await invokeBrowser("wait", browserParams("wait", { intent: "read", ms: 600 }), signal, 30);
        }
        const observed = await invokeBrowser("sectionState", browserParams("sectionState", { intent: "read", domain }), signal, 90);
        await rememberSectionRoute(String(observed.url ?? observed.page?.url ?? base), domain);
        // Browser policy has already proved canonical event identity on this
        // exact route, including legitimate keyless planner transitions.
        const comparison = compactSectionComparison(domain, expected, observed);
        await appendActivity(`Collected complete ${domain} section state in one bounded mission: ${comparison.counts.PRESENT} present, ${comparison.counts.DIFFERS} differing, ${comparison.counts.MISSING} missing`);
        return toolText({ ok: true, route: observed.url ?? observed.page?.url ?? navigation.page?.url ?? base, ...comparison });
      });
    },
  });

  pi.registerTool({
    name: "cvent_execute_section",
    label: "Execute trusted Cvent section procedure",
    description: "Run one application-owned, bounded multi-step Ego procedure for an entire RR section. Pi supplies only the section enum; trusted code loads VERIFIED RR data and owns routes, locators, actions, saves, and final readback.",
    parameters: Type.Object({ domain: literalUnion(Object.keys(TRUSTED_SECTION_PROCEDURES)) }),
    async execute(_id: string, params: any, signal: AbortSignal) {
      const domain = String(params.domain);
      const operation = TRUSTED_SECTION_PROCEDURES[domain];
      if (!operation) throw new Error(`No trusted Cvent procedure is registered for ${domain}`);
      return withQueue("browser", async () => {
        await assertSnapshotConsumed();
        if (await pendingWriteReadback()) throw new Error("Complete the pending Cvent write readback before starting a trusted section procedure");
        const expected = await verifiedCompiledExpectations();
        await assertDomainEvidenceVerified(domain);
        const holds = await replayHolds(domain);
        const heldIdentities = new Set(holds.map((hold: any) => cleanText(hold.identity, 500).toLowerCase()));
        const records = trustedProcedureRecords(domain, expected).filter((record: any) => !heldIdentities.has(cleanText(record.code, 500).toLowerCase()));
        if (!records.length) return toolText({ ok: true, domain, status: "ALREADY_CORRECT", records: [], replayHolds: holds, detail: "RR contains no non-held records for this section" });
        await updateBrowserProgress(`Running trusted multi-step Ego procedure for ${domain}`);
        const started = performance.now();
        const result = await invokeBrowser(operation, {
          intent: "write", rrSource: `VERIFIED RR domain: ${domain}`, records, timeoutSeconds: 780,
        }, signal, 780);
        await appendPerformance("trusted_section_procedure", started, { domain, operation, records: records.length,
          status: result.status, mutationCount: result.mutationCount ?? 0, metrics: result.metrics, counts: result.counts });
        await atomicJson(join(jobDir, `trusted-${domain}-result.json`), { ...result,
          rrSha256: expected.rr?.sha256, recordedAt: new Date().toISOString() });
        await appendActivity(`Trusted ${domain} Ego mission returned ${result.status}: ${result.records?.length ?? 0} records, ${result.mutationCount ?? 0} mutations`);
        await updateBrowserProgress(result.status === "AUTH_REQUIRED" ? `Cvent authentication required while entering ${domain}` : `Trusted ${domain} mission finished: ${result.status}`);
        return toolText({ ok: true, domain, replayHolds: holds, ...result });
      });
    },
  });

  pi.registerTool({
    name: "cvent_browser",
    label: "General Cvent Ego browser",
    description: "Ego's read/write browser operator for the exact selected Cvent event. Observe once with snapshotText for semantic DOM or screenshot for visual/virtualized UI, then use operation=actions for substantial predictable progress—normally many click/fill/select/keyboard/save/readback steps, potentially across multiple exact records—in one Ego process. Copy refs from the newest snapshot. Primitive operations are exceptional and only for genuinely unpredictable next state. The gateway independently enforces RR provenance, lease/lifecycle, target identity, protected-action blocks, auditing, and uncertain-write holds.",
    parameters: Type.Object({
      operation: Type.Union(PI_BROWSER_OPERATION_NAMES.map((name) => Type.Literal(name))),
      ...browserActionFields,
      objective: Type.Optional(Type.String({ minLength: 1, maxLength: 1200 })),
      commitMode: Type.Optional(Type.Union([Type.Literal("save"), Type.Literal("autosave"), Type.Literal("read_only")])),
      steps: Type.Optional(Type.Array(egoActionSchema, { minItems: 1, maxItems: 80 })),
      maxScrolls: Type.Optional(Type.Integer({ minimum: 1, maximum: 60 })),
    }),
    async execute(_id: string, params: any, signal: AbortSignal) {
      const operation = String(params.operation);
      if (operation !== "actions") validateGeneralBrowserAction(operation, params);
      return withQueue("browser", async () => {
        if (operation === "actions") {
          const domain = String(params.domain ?? ""), steps = params.steps as any[] | undefined;
          if (!DOMAINS.has(domain) || !params.objective || !params.commitMode || !steps?.length) throw new Error("A coherent Ego action round requires domain, objective, commitMode, and steps");
          const writeIndexes = steps.flatMap((step, index) => step.intent === "write" ? [index] : []);
          if (params.commitMode === "read_only" && writeIndexes.length) throw new Error("Read-only Ego action round cannot contain writes");
          if (params.commitMode !== "read_only" && !writeIndexes.length) throw new Error("Configuration Ego action round contains no writes");
          validateActionRound(params.commitMode, steps);
          await assertSnapshotConsumed();
          if (writeIndexes.length) {
            await assertCompiledExpectations();
            await assertSourcesVerified(domain, writeIndexes.map(index => steps[index].rrSource));
            await assertNoHeldReplay(domain, params);
            const pending = await pendingWriteReadback() ?? {};
            await atomicJson(WRITE_READBACK_PENDING, {
              operations: [...(pending.operations ?? []), ...writeIndexes.map(index => steps[index].operation)].slice(-100),
              rrSources: [...(pending.rrSources ?? []), ...writeIndexes.map(index => cleanText(steps[index].rrSource, 500))].slice(-100),
              requiredAt: pending.requiredAt ?? new Date().toISOString(), updatedAt: new Date().toISOString(),
            });
          }
          await updateBrowserProgress(`Ego executing coherent ${domain} work: ${cleanText(params.objective, 500)}`);
          const boundedSteps = steps.map(step => ({ operation: String(step.operation), ...browserParams(String(step.operation), step) }));
          const result = await invokeBrowser("actions", { intent: writeIndexes.length ? "write" : "read", domain, objective: cleanText(params.objective, 1200), commitMode: params.commitMode, steps: boundedSteps }, signal, Number(params.timeoutSeconds ?? 780));
          if (writeIndexes.length) await clearWriteReadback();
          await appendPerformance("ego_execution_round", performance.now(), { domain, actionCount: steps.length, writeCount: writeIndexes.length, fullSnapshots: steps.filter(step => step.operation === "snapshotText").length });
          await appendPerformance("EGO_ROUND_ACTION_DENSITY", performance.now(), { domain, actionCount: steps.length, writeCount: writeIndexes.length, objective: cleanText(params.objective, 500) });
          if (steps.length < 4) await appendPerformance("LOW_ACTION_DENSITY", performance.now(), { domain, actionCount: steps.length, commitMode: params.commitMode, objective: cleanText(params.objective, 500) });
          await appendActivity(`Ego ${domain} round completed ${steps.length} continuous browser actions: ${cleanText(params.objective, 500)}`);
          await updateBrowserProgress(`Ego ${domain} round verified and returned`);
          return toolBrowserResult(result);
        }
        const write = params.intent === "write";
        await updateBrowserProgress(write ? `Validating scoped Cvent write: ${operation}` : `Reading Cvent browser: ${operation}`);
        try {
          await assertSnapshotConsumed();
          const readback = await pendingWriteReadback();
          const readbackOperation = ["snapshotText", "readTarget", "controlInventory"].includes(operation);
          if (readback && ["navigate", "openAuthorizedEvent", "scanEventList"].includes(operation)) {
            throw new Error("Verify pending Cvent configuration changes before leaving the current page");
          }
          if (write) {
            await assertCompiledExpectations();
            if (!params.domain) throw new Error("Every adaptive Cvent write requires its validated RR domain");
            await assertSourcesVerified(String(params.domain), [params.rrSource]);
            await assertNoHeldReplay(String(params.domain), params);
          }
          const input = browserParams(operation, params);
          const timeout = Math.max(1, Math.min(Number(params.timeoutSeconds ?? (operation === "recover" ? 35 : 90)), operation === "recover" ? 35 : 180));
          const result = await invokeBrowser(operation, input, signal, timeout);
          if (operation === "navigate" && params.url) await rememberSectionRoute(String(params.url));
          const packaged = await saveLargeSnapshot(result);
          if (write) {
            const pending = readback ?? {};
            await atomicJson(WRITE_READBACK_PENDING, {
              operations: [...(pending.operations ?? []), operation].slice(-100),
              rrSources: [...(pending.rrSources ?? []), ...(params.rrSource ? [cleanText(params.rrSource, 500)] : [])].slice(-100),
              browserRuntimeId: result.browserRuntimeId, targetId: result.targetId,
              requiredAt: pending.requiredAt ?? new Date().toISOString(), updatedAt: new Date().toISOString(),
            });
          } else if (readback && readbackOperation) {
            const transport = await pendingSnapshot();
            if (!transport || transport.complete === true) await clearWriteReadback();
          }
          await updateBrowserProgress(write ? `Configuring selected Cvent event: ${operation}` : `Cvent browser read complete: ${operation}`);
          return toolBrowserResult(packaged);
        } catch (error) {
          await updateBrowserProgress(`${write ? "Cvent write" : "Cvent browser read"} blocked safely during ${operation}`);
          throw error;
        }
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
        if (complete && await pendingWriteReadback()) await clearWriteReadback();
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
      status: Type.Union([
        Type.Literal("DRAFT_COMPLETE"), Type.Literal("REVIEW_REQUIRED"), Type.Literal("INCOMPLETE"),
      ], { description: "Final controlled outcome, not an item-level exception" }),
      jobWideBlocker: Type.Optional(literalUnion(["authentication_unavailable", "wrong_event", "lease_lost", "provider_unavailable", "uncertain_mutation", "browser_runtime_failure", "capability_unavailable"])),
      blockerEvidence: Type.Optional(Type.String({ minLength: 10, maxLength: 3000 })),
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
      if (await pendingWriteReadback() && params.jobWideBlocker !== "uncertain_mutation") throw new Error("Final report blocked until the required Cvent write readback is complete");
      if (params.jobWideBlocker && (params.status !== "INCOMPLETE" || !params.blockerEvidence)) throw new Error("A genuine job-wide blocker requires INCOMPLETE and exact blocker evidence");
      if ([params.guardrails.published, params.guardrails.emailsSent, params.guardrails.deletes, params.guardrails.globalMutations].some((value) => value !== 0)) {
        throw new Error("Final report blocked: protected actions must remain zero");
      }
      if (params.status === "DRAFT_COMPLETE" && params.unresolvedItems.length) throw new Error("DRAFT_COMPLETE cannot contain unresolved RR configuration items");
      return withQueue("job-files", async () => {
        const validation = await readJson(join(jobDir, "rr-validation.json"), { items: [] });
        const verification = await readJson(join(jobDir, "final-verification.json"), { schemaVersion: 1, domains: {} });
        if (!params.jobWideBlocker) {
          if (!validation.items?.length) throw new Error("Cannot finish: verified RR plan is absent/empty; prepare the actual RR first");
          const outstanding = [...new Set(validation.items.map((item: any) => item.domain))].filter((domain: any) => !verification.domains?.[domain]?.cventEvidence?.length);
          if (outstanding.length) throw new Error(`Do not finish early. Inspect and attempt independent safe work in: ${outstanding.join(", ")}. Hold only uncertain items, not the job.`);
          if (params.status === "INCOMPLETE") throw new Error("INCOMPLETE requires a genuine job-wide blocker; use REVIEW_REQUIRED only after all independent work and final verification");
        }
        const recorded = new Map<string, any>();
        for (const domain of Object.values(verification.domains ?? {}) as any[]) for (const item of domain.items ?? []) recorded.set(item.itemId, item);
        for (const rrItem of validation.items ?? []) if (!recorded.has(rrItem.itemId)) recorded.set(rrItem.itemId, {
          itemId: rrItem.itemId, rrStatus: rrItem.status, status: rrItem.status === "AMBIGUOUS" ? "AMBIGUOUS" : "NOT_CONFIGURED",
          reason: "Domain was not verified before the job ended",
        });
        const accuracy: Record<string, number> = { MATCH: 0, NOT_CONFIGURED: 0, AMBIGUOUS: 0, PROHIBITED: 0 };
        for (const item of recorded.values()) accuracy[item.status] = (accuracy[item.status] ?? 0) + 1;
        verification.finalItems = [...recorded.values()]; verification.counts = accuracy; verification.updatedAt = new Date().toISOString();
        await atomicJson(join(jobDir, "final-verification.json"), verification);
        if (params.status === "DRAFT_COMPLETE" && (accuracy.NOT_CONFIGURED || accuracy.AMBIGUOUS || accuracy.PROHIBITED)) {
          throw new Error("DRAFT_COMPLETE requires every RR item to be MATCH");
        }
        const report = {
          status: params.status,
          job_wide_blocker: params.jobWideBlocker ?? null,
          completion_reason: params.blockerEvidence ?? "All populated RR domains assessed and verified",
          unresolved_items: params.unresolvedItems,
          real_reads: params.realReads,
          real_writes: params.realWrites,
          accuracy,
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
        if (params.status === "INCOMPLETE") state.status = "incomplete";
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
