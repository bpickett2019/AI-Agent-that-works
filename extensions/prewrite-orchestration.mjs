// Controller-only helpers. No browser operations, credentials, or profile changes.
export function retainJobContext(messages, recentCount = 20) {
  if (messages.length <= recentCount + 4) return messages;
  const blocks = [];
  for (const message of messages) {
    if (message.role === 'toolResult' && blocks.length) blocks.at(-1).push(message);
    else blocks.push([message]);
  }
  const calls = blocks.flatMap(block => (block[0].content ?? []));
  const lastDomain = [...calls].reverse().find(call =>
    call.type === 'toolCall' && ['cvent_plan', 'cvent_expectations'].includes(call.name) &&
    !['summary', 'mission', 'protected', 'gaps'].includes(call.arguments?.section))?.arguments?.section;
  let recentStart = blocks.length, count = 0;
  while (recentStart > 0 && count < recentCount) count += blocks[--recentStart].length;
  return blocks.filter((block, index) => {
    if (index >= recentStart || block[0].role === 'user' || block[0].role === 'compactionSummary') return true;
    const results = block.slice(1).filter(result => !result.isError);
    return (Array.isArray(block[0].content) ? block[0].content : []).some(call => {
      if (call.type !== 'toolCall' || !results.some(result => result.toolCallId === call.id)) return false;
      if (call.name === 'read' && call.arguments?.path?.endsWith('ego-browser/SKILL.md')) return true;
      if (call.name === 'cvent_prepare_rr' || call.name === 'cvent_login_handoff') return true;
      if (['cvent_plan', 'cvent_expectations'].includes(call.name))
        return ['summary', 'mission', lastDomain].includes(call.arguments?.section);
      return call.name === 'cvent_browser' && ['authorizeTarget', 'openAuthorizedEvent'].includes(call.arguments?.operation);
    });
  }).flat();
}

export class ValidatedRRCache {
  key = null;
  value = null;
  async get(revision, load) {
    const key = await revision();
    if (this.key === key) return this.value;
    // Invalidate before loading: a rejected refresh must never return old data.
    this.key = null;
    this.value = null;
    const value = await load();
    if (key !== await revision()) throw new Error('RR artifacts changed during validation');
    this.value = value;
    this.key = key;
    return value;
  }
}

export function normalizedDomainStatus(value) {
  return String(value ?? '').trim().toUpperCase();
}

export function firstIncompleteDomain(plan, domainResults = {}, verification = {}, state = {}) {
  const assessed = new Set();
  for (const [domain, result] of Object.entries(domainResults?.domains ?? {})) {
    if (['COMPLETE', 'COMPLETED', 'REVIEW_REQUIRED'].includes(normalizedDomainStatus(result?.checkpoint ?? result?.status))) assessed.add(domain);
  }
  for (const [domain, result] of Object.entries(verification?.domains ?? {})) {
    if (Array.isArray(result?.cventEvidence) && result.cventEvidence.length) assessed.add(domain);
  }
  for (const domain of state?.completed ?? []) assessed.add(domain);
  return (plan?.mission ?? []).map(item => item?.domain).find(domain => domain && !assessed.has(domain)) ?? null;
}

export function staleRefWithoutWrite(message) {
  const text = String(message ?? '');
  return /(?:ElementResolutionError:\s*)?Unknown ref:\s*\d+/i.test(text) && /dispatched writes=0/i.test(text);
}

export function adapterNeedsNativeFallback(result) {
  return result?.status === 'CONTROL_NOT_FOUND' && Number(result?.mutationCount ?? 0) === 0;
}

export class DomainProgressGuard {
  constructor(limit = 3) { this.limit = limit; this.domains = new Map(); }
  observe(domain, meaningful, signature = '') {
    const previous = this.domains.get(domain) ?? { consecutive: 0, maximum: 0, signature: '', strategyRequired: false };
    const changed = Boolean(signature && signature !== previous.signature);
    const madeProgress = Boolean(meaningful || changed);
    const consecutive = madeProgress ? 0 : previous.consecutive + 1;
    const next = { consecutive, maximum: Math.max(previous.maximum, consecutive), signature: signature || previous.signature,
      strategyRequired: consecutive >= this.limit };
    this.domains.set(domain, next);
    return { ...next, meaningful: madeProgress, stalled: next.strategyRequired };
  }
  requireStrategy(domain) { return Boolean(this.domains.get(domain)?.strategyRequired); }
  strategyChanged(domain) {
    const previous = this.domains.get(domain) ?? { maximum: 0, signature: '' };
    this.domains.set(domain, { ...previous, consecutive: 0, strategyRequired: false });
  }
}

export class BrowserRecoveryBudget {
  firstFailure = null;
  terminalFailure = null;
  recoveryAttempted = false;
  deniedCalls = 0;
  failure(operation, message) {
    // Model-authored script syntax/helper mistakes are item/round errors, not
    // proof that Chromium or the adapter runtime has failed.
    if (operation === 'script' && /SyntaxError:|ReferenceError:/.test(message)) return;
    // Locator/schema/evidence errors remain recoverable by normal model work.
    const runtimeError = /ReferenceError:|SyntaxError:|TimeoutError:|timeout:|timed out|Page crashed|Browser action gate is occupied|renderer did not recover|helper returned no structured result|Steel resource admission denied/i.test(message);
    if (!runtimeError && operation !== 'recover') return;
    this.firstFailure ??= { operation, message };
    if (operation === 'recover' || this.recoveryAttempted || /ReferenceError:|SyntaxError:|Browser action gate is occupied|Steel resource admission denied/i.test(message))
      this.terminalFailure = { first: this.firstFailure, operation, message };
  }
  allow(toolName, input) {
    if (!this.firstFailure) return { allowed: true };
    if (this.terminalFailure) return { allowed: false, terminal: true };
    if (toolName === 'cvent_browser' && input?.operation === 'recover' && input.intent === 'read' && !this.recoveryAttempted) {
      this.recoveryAttempted = true;
      return { allowed: true, recovery: true };
    }
    if (++this.deniedCalls >= 2) {
      this.terminalFailure = { first: this.firstFailure, operation: 'controller', message: 'Runtime recovery boundary ignored twice' };
      return { allowed: false, terminal: true };
    }
    return { allowed: false, terminal: false };
  }
  recovered() {
    // Do not grant an unlimited budget by alternating success and timeout.
    this.firstFailure = null;
    this.terminalFailure = null;
  }
}
