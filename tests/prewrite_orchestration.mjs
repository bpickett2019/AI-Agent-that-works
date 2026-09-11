// Entirely offline regression: no Anthropic requests and no Cvent/browser connections.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import { createHash } from 'node:crypto';
import { retainJobContext, ValidatedRRCache, BrowserRecoveryBudget } from '../extensions/prewrite-orchestration.mjs';

const pair = (id, name, args = {}, text = '{}') => [
  { role: 'assistant', content: [{ type: 'toolCall', id, name, arguments: args }] },
  { role: 'toolResult', toolCallId: id, toolName: name, content: [{ type: 'text', text }], isError: false },
];
const setup = pair('setup', 'cvent_prepare_rr');
const mission = pair('mission', 'cvent_plan', { section: 'mission' });
const summary = pair('summary', 'cvent_plan', { section: 'summary' });
const handoff = pair('handoff', 'cvent_login_handoff');
const messages = [{ role: 'user', content: 'job' }, ...setup, ...mission, ...summary, ...handoff,
  ...Array.from({ length: 30 }, (_, i) => pair(`recovery-${i}`, 'cvent_job_read')).flat()];
const retained = retainJobContext(messages);
assert(retained.length < messages.length);
for (const message of [...setup, ...mission, ...summary, ...handoff]) assert(retained.includes(message));
for (const result of retained.filter(message => message.role === 'toolResult'))
  assert(retained.some(message => Array.isArray(message.content) && message.content.some(call => call.id === result.toolCallId)));

const cache = new ValidatedRRCache();
let revision = 'one', loads = 0;
const load = async () => ({ count: ++loads });
assert.equal(await cache.get(async () => revision, load), await cache.get(async () => revision, load));
assert.equal(loads, 1);
revision = 'two';
assert.equal((await cache.get(async () => revision, load)).count, 2);
revision = 'bad';
await assert.rejects(cache.get(async () => revision, async () => { throw Error('stale'); }), /stale/);
await assert.rejects(cache.get(async () => revision, async () => { revision = 'changed'; return {}; }), /changed during validation/);

for (const message of ['ReferenceError: actionIndex is not defined', 'Browser action gate is occupied', 'Steel resource admission denied: Docker host is undersized']) {
  const budget = new BrowserRecoveryBudget(); budget.failure('openAuthorizedEvent', message);
  assert.deepEqual(budget.allow('cvent_prepare_rr', {}), { allowed: false, terminal: true });
}
const budget = new BrowserRecoveryBudget();
budget.failure('authStatus', 'timeout: timed out');
assert.equal(budget.allow('cvent_login_handoff', {}).allowed, false);
assert.equal(budget.allow('cvent_browser', { operation: 'recover', intent: 'read' }).recovery, true);
budget.recovered();
budget.failure('pageInfo', 'TimeoutError:');
assert.equal(budget.allow('cvent_browser', { operation: 'recover', intent: 'read' }).terminal, true);
const invalid = new BrowserRecoveryBudget(); invalid.failure('authStatus', 'timeout: timed out');
assert.equal(invalid.allow('cvent_plan', {}).terminal, false);
assert.equal(invalid.allow('cvent_prepare_rr', {}).terminal, true);
const locator = new BrowserRecoveryBudget(); locator.failure('fill', 'target could not be resolved');
assert.equal(locator.allow('cvent_browser', { operation: 'snapshotText' }).allowed, true);

const root = process.cwd(), directory = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'prewrite-offline-'));
try {
  const helperRoot = path.join(directory, 'fake-helper'); fs.mkdirSync(helperRoot);
  Object.assign(process.env, { CVENT_JOB_DIR: directory, CVENT_REPO_ROOT: helperRoot,
    CVENT_AUTHORIZED_EVENT_ID: 'test-event', CVENT_AUTHORIZED_EVENT_KEY: 'test-event', CVENT_AUTHORIZED_EVENT_NAME: 'Test Event',
    CVENT_LEASE_VALIDATE_URL: 'http://unused.invalid', CVENT_LEASE_TOKEN: 'offline-test-token' });
  const input = Buffer.from('offline workbook');
  const sha256 = createHash('sha256').update(input).digest('hex');
  const target = { eventId: 'test-event', eventKey: 'test-event', name: 'Test Event' };
  const save = (name, data) => fs.writeFileSync(path.join(directory, name), JSON.stringify(data));
  fs.writeFileSync(path.join(directory, 'input.xlsx'), input);
  save('expected-domains.json', { rr: { sha256, authority: 'uploaded_rr' }, target, counts: { applicableFields: 1 } });
  save('configuration-plan.json', { rrSha256: sha256, target, mission: [{ order: 1, domain: 'event_settings', verifiedItemIds: ['one'], heldItems: [] }] });
  save('rr-validation.json', { rrSha256: sha256, items: [{ domain: 'event_settings', itemId: 'one', status: 'VERIFIED' }] });
  save('browser-runtime.json', { browserRuntimeId: 'offline-runtime' });
  fs.writeFileSync(path.join(helperRoot, 'browser_tool.py'), 'import sys\nprint(\'BROWSER_ROUTER_RESULT={"ok":false,"error":"timeout: timed out"}\')\nsys.exit(1)\n');
  const require = createRequire(import.meta.url);
  let source = stripTypeScriptTypes(fs.readFileSync(path.join(root, 'extensions/cvent-job-tools.ts'), 'utf8'));
  source = source.replace('"typebox"', JSON.stringify(pathToFileURL(require.resolve('typebox')).href))
    .replace('"./prewrite-orchestration.mjs"', JSON.stringify(pathToFileURL(path.join(root, 'extensions/prewrite-orchestration.mjs')).href));
  const extension = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const tools = new Map(), hooks = new Map();
  extension.default({ on: (name, handler) => hooks.set(name, handler), registerTool: tool => tools.set(tool.name, tool), setActiveTools() {} });
  const prepare = tools.get('cvent_prepare_rr');
  const first = JSON.parse((await prepare.execute('prepare', {}, undefined)).content[0].text);
  assert.equal(first.firstDomain, 'event_settings'); assert.equal(first.items.length, 1);
  const second = JSON.parse((await prepare.execute('prepare-again', {}, undefined)).content[0].text);
  assert.equal(second.alreadyPrepared, true);
  assert.equal(fs.readFileSync(path.join(directory, 'activity.log'), 'utf8').trim().split('\n').length, 1);
  // A changed workbook must invalidate a warm cache; no stale data or write bypass.
  fs.writeFileSync(path.join(directory, 'input.xlsx'), 'changed');
  await assert.rejects(tools.get('cvent_plan').execute('stale', { section: 'summary' }), /stale or belong/);
  fs.writeFileSync(path.join(directory, 'input.xlsx'), input);
  await tools.get('cvent_plan').execute('fresh', { section: 'summary' });
  assert(tools.has('read') && tools.has('bash'));
  await assert.rejects(tools.get('bash').execute('shell', { command: 'env' }), /Use only ego-browser/);
  const finalArgs = { status: 'REVIEW_REQUIRED', unresolvedItems: ['one item ambiguous'], realReads: [], realWrites: [],
    guardrails: { published: 0, emailsSent: 0, deletes: 0, globalMutations: 0 } };
  await assert.rejects(tools.get('cvent_finish').execute('early', finalArgs), /Do not finish early/);
  save('rr-validation.json', { rrSha256: sha256, items: [
    { domain: 'event_settings', itemId: 'one', status: 'VERIFIED', sourceEvidence: {sheet:'RR',range:'B1'} },
    { domain: 'event_settings', itemId: 'two', status: 'AMBIGUOUS', sourceEvidence: {sheet:'RR',range:'B2'} },
  ] });
  const helper = path.join(helperRoot, 'browser_tool.py');
  const failedHelper = fs.readFileSync(helper, 'utf8');
  fs.writeFileSync(helper, 'print(\'BROWSER_ROUTER_RESULT={"ok":true,"actionCount":4,"writesAttempted":2,"saves":1,"readbacks":1}\')');
  const native = source => ({ command: `ego-browser nodejs <<'EOF'\n// cvent: {"domain":"event_settings","commitMode":"save","rrSources":["${source}"]}\nawait fillInput('@1','value'); await click('@2'); cliLog(await snapshotText());\nEOF` });
  await tools.get('bash').execute('independent-safe-write', native('RR!B1'));
  await assert.rejects(tools.get('bash').execute('ambiguous-write', native('RR!B2')), /Item held/);
  save('final-verification.json', { domains: {event_settings: {cventEvidence:['actual page'],items:[]}} });
  assert.equal((await tools.get('cvent_finish').execute('review-after-work', finalArgs)).terminate, true);
  fs.writeFileSync(helper, failedHelper);
  await assert.rejects(tools.get('cvent_browser').execute('auth', { operation: 'authStatus', intent: 'read' }, undefined), /timeout: timed out/);
  const hook = hooks.get('tool_call');
  assert.equal((await hook({ toolName: 'cvent_login_handoff', input: {} })).block, true);
  const recovery = { toolName: 'cvent_browser', input: { operation: 'recover', intent: 'read', timeoutSeconds: 240 } };
  assert.equal(await hook(recovery), undefined); assert.equal(recovery.input.timeoutSeconds, 30);
  await assert.rejects(tools.get('cvent_browser').execute('recover', recovery.input, undefined), /timeout: timed out/);
  assert.equal((await hook({ toolName: 'cvent_prepare_rr', input: {} })).terminate, true);
  const failure = JSON.parse(fs.readFileSync(path.join(directory, `controller-failure-${process.pid}.json`), 'utf8'));
  assert.equal(failure.first.operation, 'authStatus'); assert.equal(failure.operation, 'recover');
  assert.match(failure.message, /timeout: timed out/);
} finally {
  fs.rmSync(directory, { recursive: true, force: true });
}
console.log('Offline prewrite orchestration regressions passed');
