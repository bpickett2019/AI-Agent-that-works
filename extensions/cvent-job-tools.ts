import { execFile } from "node:child_process";
import { randomUUID, createHash } from "node:crypto";
import { open, readFile, realpath, rename, mkdir, appendFile, lstat, unlink } from "node:fs/promises";
import { join, resolve } from "node:path";
import { Type } from "typebox";

const BROWSER_OPERATION_NAMES = [
  "probe", "recover", "authStatus", "authorizeTarget", "openAuthorizedEvent", "snapshotText", "readTarget", "sectionState", "controlInventory", "pageInfo", "scanEventList",
  "scroll", "click", "activate", "fill", "type", "navigate", "wait", "hover", "selectOption", "setChecked", "press", "search", "selectText", "drag", "uploadDiscountImport",
];
const PI_BROWSER_OPERATION_NAMES = BROWSER_OPERATION_NAMES;
const EGO_ACTION_OPERATIONS = ["pageInfo", "snapshotText", "readTarget", "sectionState", "controlInventory", "scroll", "click", "activate", "fill", "type", "navigate", "wait", "hover", "selectOption", "setChecked", "press", "search", "selectText", "drag", "uploadDiscountImport"] as const;
const TRUSTED_SECTION_PROCEDURES: Record<string, string> = {
  admission_items: "configureAdmissionItems", registration_types: "configureRegistrationTypes",
};
const BROWSER_OPERATIONS = new Set(BROWSER_OPERATION_NAMES);
const READ_ONLY_OPERATIONS = new Set([
  "probe", "recover", "authStatus", "authorizeTarget", "openAuthorizedEvent", "snapshotText", "readTarget", "sectionState", "controlInventory", "pageInfo", "scanEventList",
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
  final_report: "final-report.json",
  domain_results: "domain-results.json",
  inspection_summary: "input.inspection-summary.json",
  browser_runtime: "browser-runtime.json",
  performance: "performance-summary.json",
};
const ALLOWED_TOOLS = new Set([
  "cvent_prepare_rr", "cvent_expectations", "cvent_plan", "cvent_job_read",
  "cvent_job_update", "cvent_record_domain", "cvent_verify_domain", "cvent_browser", "cvent_ego_actions", "cvent_section_state", "cvent_execute_section",
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
  const timeout = Math.max(1, Math.min(timeoutSeconds, trusted ? 900 : operation === "recover" ? 300 : 180));
  const boundedParams = { ...params, timeoutSeconds: timeout };
  const output = await runFixed(python, [
    join(repoRoot, "browser_tool.py"), "--runtime", runtimePath, "--tool", "ego",
    "--operation", operation, "--params", JSON.stringify(boundedParams),
  ], "browser", signal, (timeout + (operation === "recover" ? 45 : trusted ? 30 : 10)) * 1000);
  const result = parseMarker(output.stdout, "BROWSER_ROUTER_RESULT=");
  await appendPerformance("browser_operation", started, { operation, intent: params.intent, navigation: ["navigate", "openAuthorizedEvent"].includes(operation), snapshot: operation === "snapshotText", fullSnapshot: operation === "snapshotText", responseBytes: Buffer.byteLength(JSON.stringify(result)) });
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

async function assertDomainEvidenceVerified(domain: string): Promise<void> {
  const validation = await readJson(join(jobDir, "rr-validation.json"), null);
  const unsupported = (validation?.items ?? []).filter((item: any) => item.domain === domain && item.status !== "VERIFIED");
  if (unsupported.length) throw new Error(`Trusted ${domain} procedure blocked: ${unsupported.length} RR evidence items are not independently VERIFIED`);
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
  if (["fill", "type", "search"].includes(operation)) params.text = cleanText(input.text, 20000);
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
  if (input.rrSource) params.rrSource = cleanText(input.rrSource, 500);
  return params;
}

function validateGeneralBrowserAction(operation: string, params: any): void {
  if (!BROWSER_OPERATIONS.has(operation)) throw new Error("Capability denied: browser operation is not approved");
  if (!new Set(["read", "write"]).has(params.intent)) throw new Error("Capability denied: explicit read or write intent is required");
  if (READ_ONLY_OPERATIONS.has(operation) && params.intent !== "read") throw new Error(`${operation} is a read-only capability`);
  if (["fill", "type", "selectOption", "setChecked", "drag", "uploadDiscountImport"].includes(operation) && params.intent !== "write") throw new Error(`${operation} requires write intent`);
  if (operation === "press" && !ALLOWED_KEYS.has(String(params.key))) throw new Error("Capability denied: keyboard key is not approved");
  if (operation === "press" && ["Backspace", "Delete"].includes(String(params.key)) && params.intent !== "write") throw new Error(`${params.key} requires write intent`);
  if (operation === "selectOption" && !["label", "value", undefined].includes(params.optionBy)) throw new Error("Capability denied: optionBy must be label or value");
  if (operation === "drag" && !params.destination) throw new Error("Capability denied: drag destination is required");
  if (params.intent === "write" && !cleanText(params.rrSource, 500)) throw new Error("Dynamic Cvent writes require verified RR source evidence");
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
  target: Type.Optional(Type.String({ maxLength: 4000, description: 'An exact target: role:<role>[name="<exact accessible name>"] or a stable CSS selector returned by controlInventory. Never use XPath-style text(), a bare element type, or snapshot prose such as menuitem "Details".' })),
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
  timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 300 })),
};
const egoActionSchema = Type.Object({ operation: literalUnion(EGO_ACTION_OPERATIONS), ...browserActionFields });

export default function cventJobTools(pi: any) {
  let turnStarted = 0;
  let firstTokenRecorded = false;
  const safeMetric = async (kind: string, started: number, details: Record<string, unknown> = {}) => {
    try { await appendPerformance(kind, started, details); } catch { /* metrics never block configuration */ }
  };
  pi.on("session_start", async () => {
    pi.setActiveTools([...ALLOWED_TOOLS]);
    await safeMetric("pi_session_start", performance.now(), { pid: process.pid });
  });
  pi.on("context", async (event: any) => {
    const messages = event.messages ?? [];
    if (messages.length <= 32) return undefined;
    const initial = messages.find((message: any) => message.role === "user");
    let start = Math.max(0, messages.length - 28);
    while (start < messages.length && messages[start]?.role === "toolResult") start += 1;
    const recent = messages.slice(start);
    const filtered = initial && !recent.includes(initial) ? [initial, ...recent] : recent;
    await safeMetric("context_pruned", performance.now(), { originalMessages: messages.length, retainedMessages: filtered.length });
    return { messages: filtered };
  });
  pi.on("turn_start", () => { turnStarted = performance.now(); firstTokenRecorded = false; });
  pi.on("message_update", async (event: any) => {
    if (!firstTokenRecorded && event.message?.role === "assistant") {
      firstTokenRecorded = true;
      await safeMetric("anthropic_first_token", turnStarted || performance.now());
    }
  });
  pi.on("message_end", async (event: any) => {
    if (event.message?.role !== "assistant") return;
    const usage = event.message.usage ?? {};
    await safeMetric("anthropic_response", turnStarted || performance.now(), {
      inputTokens: usage.input ?? 0, outputTokens: usage.output ?? 0,
      cacheReadTokens: usage.cacheRead ?? 0, cacheWriteTokens: usage.cacheWrite ?? 0,
      totalTokens: usage.totalTokens ?? 0,
    });
  });
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
    description: "Inspect the uploaded RR and compile its event-configuration requirements using fixed server helpers. Takes no paths or commands.",
    parameters: Type.Object({}),
    async execute(_id: string, _params: unknown, signal: AbortSignal) {
      return withQueue("job-files", async () => {
        await readJobFile(join(jobDir, "input.xlsx"), 25 * 1024 * 1024);
        try {
          const existing = await verifiedCompiledExpectations();
          await appendActivity(`RR preflight reverified ${existing.counts?.applicableFields ?? 0} writable configuration fields`);
          return toolText({ ok: true, reusedPreflight: true, counts: existing.counts, identifiers: existing.identifierRegistry });
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
        if (!pageUrl || pageUrl === "about:blank" || !recognizedLoginHost) {
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
            return toolText({ ok: true, resumed: true, profilePersisted: true,
              instruction: "Forge verified and persisted this slot's Cvent login. Fresh-read pageInfo and a complete snapshot before continuing." });
          }
          if (current.ownership === "NONE") throw new Error("Browser return was blocked; human review is required");
        }
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
        const liveUrl = String(observed.url ?? observed.page?.url ?? "").toLowerCase();
        if (!liveUrl.includes(requiredEnvironment("CVENT_AUTHORIZED_EVENT_KEY").toLowerCase())) {
          throw new Error("CVENT_AUTH_REQUIRED_OR_EVENT_ROUTE_LOST: hand off only if the fresh auth check confirms login is required");
        }
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
        const records = trustedProcedureRecords(domain, expected);
        if (!records.length) return toolText({ ok: true, domain, status: "ALREADY_CORRECT", records: [], detail: "RR contains no records for this section" });
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
        return toolText({ ok: true, domain, ...result });
      });
    },
  });

  pi.registerTool({
    name: "cvent_ego_actions",
    label: "Execute adaptive Ego actions",
    description: "Execute one model-planned, bounded sequence of ordinary Ego browser actions against the exact authorized event. Use exact role:<role>[name=\"<accessible name>\"] targets or stable CSS from controlInventory. Entering a section or edit mode is a read_only mission; changing configuration is a save/autosave mission. A save mission must include the actual explicit Save click/press followed by readback—not merely an Edit click. Group an editor's actions without a Claude round-trip per primitive. Safety, lease, lifecycle, target preflight, write audit, uncertainty, and protected-action blocks apply to every step. Specialized section procedures are optional optimizations, not prerequisites.",
    parameters: Type.Object({
      domain: literalUnion(DOMAIN_NAMES),
      objective: Type.String({ minLength: 1, maxLength: 1200 }),
      commitMode: Type.Union([Type.Literal("save"), Type.Literal("autosave"), Type.Literal("read_only")]),
      steps: Type.Array(egoActionSchema, { minItems: 1, maxItems: 80 }),
    }),
    async execute(_id: string, params: any, signal: AbortSignal) {
      return withQueue("browser", async () => {
        await assertSnapshotConsumed();
        const domain = String(params.domain), steps = params.steps as any[];
        const writeIndexes = steps.flatMap((step, index) => step.intent === "write" ? [index] : []);
        if (params.commitMode === "read_only" && writeIndexes.length) throw new Error("Read-only Ego action mission cannot contain writes");
        if (params.commitMode !== "read_only" && !writeIndexes.length) throw new Error("Configuration Ego action mission contains no writes");
        if (writeIndexes.length) {
          await assertCompiledExpectations();
          await assertDomainEvidenceVerified(domain);
          const lastWrite = writeIndexes[writeIndexes.length - 1];
          const readbacks = new Set(["readTarget", "sectionState", "controlInventory", "snapshotText"]);
          if (!steps.slice(lastWrite + 1).some(step => step.intent === "read" && readbacks.has(step.operation))) {
            throw new Error("Adaptive Ego write mission requires an explicit post-write readback step");
          }
          if (steps.slice(writeIndexes[0] + 1).some(step => step.operation === "navigate")) {
            throw new Error("Adaptive Ego write mission cannot navigate away before Claude evaluates its readback");
          }
          if (params.commitMode === "save" && !steps.some(step => step.intent === "write" && ["click", "activate", "press"].includes(step.operation) && /save/i.test(String(step.target ?? step.key ?? "")))) {
            throw new Error("Adaptive Ego save mission requires an explicit reviewed Save action");
          }
        }
        await updateBrowserProgress(`Ego dynamically executing ${domain}: ${cleanText(params.objective, 500)}`);
        const results: any[] = [];
        for (let index = 0; index < steps.length; index++) {
          const step = steps[index], operation = String(step.operation);
          validateGeneralBrowserAction(operation, step);
          if (step.intent === "write") {
            const pending = await pendingWriteReadback() ?? {};
            await atomicJson(WRITE_READBACK_PENDING, {
              operations: [...(pending.operations ?? []), operation].slice(-100),
              rrSources: [...(pending.rrSources ?? []), cleanText(step.rrSource, 500)].slice(-100),
              requiredAt: pending.requiredAt ?? new Date().toISOString(), updatedAt: new Date().toISOString(),
            });
          }
          const result = await invokeBrowser(operation, browserParams(operation, step), signal, Number(step.timeoutSeconds ?? 90));
          results.push({ index, operation, intent: step.intent, result });
        }
        if (writeIndexes.length) await clearWriteReadback();
        await appendActivity(`Adaptive Ego ${domain} mission completed ${steps.length} browser actions in one model tool call: ${cleanText(params.objective, 500)}`);
        await updateBrowserProgress(`Adaptive Ego ${domain} mission returned with post-write readback`);
        return toolText({ ok: true, domain, objective: params.objective, commitMode: params.commitMode, actions: results });
      });
    },
  });

  pi.registerTool({
    name: "cvent_browser",
    label: "General Cvent Ego browser",
    description: "Dynamically inspect and operate the real Cvent UI in the canonical browser. Ordinary exact-event navigation, create/update controls, Save, and readback are available; the application independently enforces RR provenance, lease/lifecycle, target preflight, auditing, uncertainty, and permanent protected-action blocks.",
    parameters: Type.Object({
      operation: Type.Union(PI_BROWSER_OPERATION_NAMES.map((name) => Type.Literal(name))),
      ...browserActionFields,
      maxScrolls: Type.Optional(Type.Integer({ minimum: 1, maximum: 60 })),
    }),
    async execute(_id: string, params: any, signal: AbortSignal) {
      const operation = String(params.operation);
      validateGeneralBrowserAction(operation, params);
      return withQueue("browser", async () => {
        const write = params.intent === "write";
        await updateBrowserProgress(write ? `Validating scoped Cvent write: ${operation}` : `Reading Cvent browser: ${operation}`);
        try {
          await assertSnapshotConsumed();
          const readback = await pendingWriteReadback();
          const readbackOperation = ["snapshotText", "readTarget", "controlInventory"].includes(operation);
          if (readback && ["navigate", "openAuthorizedEvent", "scanEventList"].includes(operation)) {
            throw new Error("Verify pending Cvent configuration changes before leaving the current page");
          }
          if (write) await assertCompiledExpectations();
          const input = browserParams(operation, params);
          const timeout = Math.max(1, Math.min(Number(params.timeoutSeconds ?? (operation === "recover" ? 240 : 90)), operation === "recover" ? 300 : 180));
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
          return toolText(packaged);
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
      ], { description: "Final controlled outcome" }),
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
      if (await pendingWriteReadback()) throw new Error("Final report blocked until the required Cvent write readback is complete");
      if ([params.guardrails.published, params.guardrails.emailsSent, params.guardrails.deletes, params.guardrails.globalMutations].some((value) => value !== 0)) {
        throw new Error("Final report blocked: protected actions must remain zero");
      }
      if (params.status === "DRAFT_COMPLETE" && params.unresolvedItems.length) throw new Error("DRAFT_COMPLETE cannot contain unresolved RR configuration items");
      return withQueue("job-files", async () => {
        const validation = await readJson(join(jobDir, "rr-validation.json"), { items: [] });
        const verification = await readJson(join(jobDir, "final-verification.json"), { schemaVersion: 1, domains: {} });
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
        if (["REVIEW_REQUIRED", "INCOMPLETE"].includes(params.status)) state.status = "review_required";
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
