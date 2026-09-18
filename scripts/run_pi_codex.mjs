#!/usr/bin/env node
/** Local Pi SDK entry: shared OAuth refresh storage, isolated job resources/tools. */
import { readFileSync, realpathSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const probe = process.argv[2] === '--probe';
let host;
try {
  if (process.env.CVENT_ENV !== 'development' || process.env.CVENT_LOCAL_CODEX !== '1' ||
      process.env.CVENT_EXECUTION_MODE !== 'simple' || process.env.CVENT_DEPLOYMENT_SCOPE ||
      process.env.CVENT_STAGING_RESTRICTED_ACCESS === '1' ||
      process.env.CVENT_PI_PROVIDER !== 'openai-codex' || process.env.CVENT_PI_MODEL !== 'gpt-6-astra') {
    throw new Error('Local Codex configuration rejected');
  }
  const { ModelRuntime, SessionManager, SettingsManager, createAgentSessionServices,
    createAgentSessionFromServices, createAgentSessionRuntime, runPrintMode } =
    await import(pathToFileURL(process.env.CVENT_PI_SDK_ENTRY).href);
  const cwd = realpathSync(process.cwd());
  const agentDir = resolve(process.env.PI_CODING_AGENT_DIR);
  if (agentDir !== join(cwd, 'pi-config')) throw new Error('Job config directory mismatch');
  mkdirSync(agentDir, { recursive: true, mode: 0o700 });
  const authPath = realpathSync(process.env.CVENT_PI_AUTH_FILE);
  // Use the canonical auth path so all Pi processes share the same OAuth refresh lock.
  // No auth symlinks, token copies, or credentials in job artifacts/tool environments.
  const modelRuntime = await ModelRuntime.create({
    authPath, modelsPath: null, modelsStorePath: join(dirname(authPath), 'models-store.json'),
    allowModelNetwork: true, modelRefreshTimeoutMs: 15000, signal: AbortSignal.timeout(20000),
  });
  const model = modelRuntime.getModel('openai-codex', 'gpt-6-astra');
  if (!model) throw new Error('Requested Astra model is unavailable; no fallback allowed');
  let settings = {};
  if (!probe) settings = JSON.parse(readFileSync(join(agentDir, 'settings.json'), 'utf8'));
  const settingsManager = SettingsManager.inMemory({ ...settings,
    defaultProvider: 'openai-codex', defaultModel: 'gpt-6-astra',
    defaultProjectTrust: 'never', enableInstallTelemetry: false,
    ...(probe ? { retry: { enabled: false } } : {}),
  });
  const tools = ['read', 'bash', 'cvent_open_event', 'cvent_login_handoff', 'cvent_job_update', 'cvent_finish'];
  const args = process.argv.slice(2);
  let sessionManager;
  let prompt;
  if (probe) {
    if (args.length !== 1) throw new Error('Invalid probe arguments');
    sessionManager = SessionManager.inMemory(cwd);
    prompt = 'Reply with exactly READY. Do not take any other action.';
  } else {
    if (args[0] !== '--job') throw new Error('Expected --job');
    const sessionDir = join(cwd, 'pi-sessions');
    if (args[1] === '--session') {
      if (args.length !== 4) throw new Error('Invalid resume arguments');
      const sessionFile = realpathSync(args[2]);
      if (dirname(sessionFile) !== realpathSync(sessionDir)) throw new Error('Session outside job');
      sessionManager = SessionManager.open(sessionFile, sessionDir);
      prompt = args[3];
    } else {
      if (args.length !== 2) throw new Error('Invalid job arguments');
      sessionManager = SessionManager.create(cwd, sessionDir);
      prompt = args[1];
    }
    sessionManager.appendSessionInfo(`cvent-${process.env.CVENT_JOB_ID}`);
  }
  const createRuntime = async ({ cwd: nextCwd, sessionManager, sessionStartEvent }) => {
    if (realpathSync(nextCwd) !== cwd) throw new Error('Changing job cwd is forbidden');
    const services = await createAgentSessionServices({ cwd, agentDir, modelRuntime, settingsManager,
      resourceLoaderOptions: {
        noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
        additionalExtensionPaths: probe ? [] : [join(repo, 'extensions/cvent-job-tools.ts')],
        additionalSkillPaths: probe ? [] : [join(repo, 'skills/ego-browser/SKILL.md')],
      },
    });
    const loaded = services.resourceLoader.getExtensions();
    if (loaded.errors.length || (!probe && loaded.extensions.length !== 1)) {
      throw new Error('Required Cvent capability extension failed to load');
    }
    const result = await createAgentSessionFromServices({ services, sessionManager, sessionStartEvent,
      model, thinkingLevel: probe ? 'off' : (process.env.CVENT_PI_THINKING || 'high'),
      noTools: probe ? 'all' : 'builtin', tools: probe ? [] : tools,
    });
    if (result.session.model?.provider !== model.provider || result.session.model?.id !== model.id) {
      result.session.dispose(); throw new Error('Unexpected model fallback');
    }
    return { ...result, services, diagnostics: services.diagnostics };
  };
  host = await createAgentSessionRuntime(createRuntime, { cwd, agentDir, sessionManager });
  if (probe) {
    await host.session.prompt(prompt);
    const last = host.session.messages.filter(m => m.role === 'assistant').at(-1);
    const text = last?.content.filter(c => c.type === 'text').map(c => c.text).join('').trim();
    if (last?.stopReason !== 'stop' || text !== 'READY') throw new Error('Codex availability probe failed');
    console.log(JSON.stringify({ ok: true, classification: 'usable', provider: model.provider, model: model.id }));
    await host.dispose(); host = undefined;
  } else {
    await runPrintMode(host, { mode: 'json', initialMessage: prompt, initialImages: [], messages: [] });
    host = undefined;
  }
} catch (error) {
  // Never print provider payloads, OAuth tokens, or authentication objects.
  if (host) await host.dispose().catch(() => {});
  console.log(JSON.stringify({ ok: false, classification: probe ? 'codex_unavailable' : 'codex_job_failed',
    errorType: error?.constructor?.name || 'Error' }));
  process.exitCode = 1;
}
