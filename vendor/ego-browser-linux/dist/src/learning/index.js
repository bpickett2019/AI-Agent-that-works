import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";
import {
  iterLearningDirs,
  learningEntry,
  loadLearningManifest,
  siteSkillsForUrl,
  siteSkillsRoot,
  urlHostname
} from "./check-domain-learning.js";
import {
  checkDomainLearningExists,
  checkLearningExists,
  iterLearningDirs as iterLearningDirs2,
  learningsRoot as learningsRoot2,
  pathExists,
  siteSkillsForUrl as siteSkillsForUrl2,
  siteSkillsRoot as siteSkillsRoot2
} from "./check-domain-learning.js";
import {
  validateLearning as validateLearning2,
  validateLearnings as validateLearnings2,
  validateSiteSkills as validateSiteSkills2
} from "./validate-learning-format.js";
async function loadLearnedContext(url, options = {}) {
  const matches = await siteSkillsForUrl(url, options);
  if (matches.length === 0) {
    return {
      exists: false,
      siteId: null,
      siteName: null,
      domain: urlHostname(url),
      knowledge: [],
      tools: []
    };
  }
  const toolSignatures = [];
  const knowledgeNotes = [];
  for (const entry of matches) {
    const siteId = entry.id;
    for (const notePath of entry.notes) {
      if (!isLearningNotePath(entry.path, notePath)) {
        continue;
      }
      let content;
      try {
        content = await readFile(notePath, "utf8");
      } catch {
        continue;
      }
      const fileName = notePath.split(/[\\/]/).pop() || "";
      knowledgeNotes.push({ siteId, fileName, content });
    }
    const nodeTools = entry.nodeTools || {};
    for (const [toolName, schema] of Object.entries(nodeTools)) {
      toolSignatures.push({
        siteId,
        toolName,
        toolType: "node",
        description: schema.description || "",
        args: schema.args || {},
        returns: schema.returns || null,
        example: `await site.runTool("${siteId}", "${toolName}", { ... })`
      });
    }
    const browserTools = entry.browserTools || {};
    for (const [toolName, schema] of Object.entries(browserTools)) {
      toolSignatures.push({
        siteId,
        toolName,
        toolType: "browser",
        description: schema.description || "",
        args: schema.args || {},
        returns: schema.returns || null,
        example: `await site.runBrowserTool("${siteId}", "${toolName}", { ... })`
      });
    }
  }
  return {
    exists: true,
    siteId: matches[0].id,
    siteName: matches[0].name,
    domain: urlHostname(url),
    knowledge: knowledgeNotes,
    tools: toolSignatures
  };
}
function isLearningNotePath(siteDir, notePath) {
  const relativePath = relative(resolve(siteDir), resolve(notePath));
  const parts = relativePath.split(/[\\/]/);
  return parts.length === 2 && parts[0] === "notes" && parts[1].endsWith(".md") && parts.every((part) => part && part !== "." && part !== "..");
}
async function findSiteSkill(siteId, options = {}) {
  const root = options.root || siteSkillsRoot(options.agentWorkspace);
  for (const siteDir of await iterLearningDirs(root)) {
    const manifest = await loadLearningManifest(siteDir);
    if (manifest.id === siteId) {
      return { siteDir, manifest };
    }
  }
  throw siteSkillNotFoundError(siteId, root);
}
async function runNodeSiteTool(siteId, toolName, args = {}, ctx, options = {}) {
  const { siteDir, manifest } = await findSiteSkill(siteId, options);
  const schema = toolSchemas(manifest, "nodeTools")[toolName];
  if (!schema || typeof schema !== "object") {
    throw new Error(
      `Node tool ${JSON.stringify(toolName)} is not declared by site skill ${JSON.stringify(siteId)}`
    );
  }
  const toolPath = relativeSitePath(siteDir, schema.path, "Node tool");
  if (process.env.EGO_BROWSER_DISABLE_SANDBOX === "1") {
    const module = await import(`${pathToFileURL(toolPath).href}?t=${Date.now()}`);
    const callableName2 = schema.callable;
    if (typeof callableName2 !== "string" || !callableName2.trim()) {
      throw new Error(
        `Node tool ${JSON.stringify(toolName)} must declare a callable`
      );
    }
    const tool = module[callableName2];
    if (typeof tool !== "function") {
      throw new Error(
        `site skill ${JSON.stringify(siteId)} is missing Node callable ${JSON.stringify(callableName2)}`
      );
    }
    return tool(ctx, args || {});
  }
  const { Worker } = await import("node:worker_threads");
  const { pathToFileURL: ptf } = await import("node:url");
  const workerCode = `
    import { parentPort, workerData } from "node:worker_threads";
    const { toolPath, callableName, args, ctx } = workerData;
    const module = await import(toolPath + "?t=" + Date.now());
    const tool = module[callableName];
    if (typeof tool !== "function") {
      parentPort.postMessage({ error: "callable " + callableName + " is not a function" });
      process.exit(1);
    }
    try {
      const result = await tool(ctx, args);
      parentPort.postMessage({ result });
    } catch (err) {
      parentPort.postMessage({ error: err.message || String(err) });
    }
  `;
  const callableName = schema.callable;
  if (typeof callableName !== "string" || !callableName.trim()) {
    throw new Error(
      `Node tool ${JSON.stringify(toolName)} must declare a callable`
    );
  }
  const toolUrl = ptf(toolPath).href;
  const timeoutMs = schema.timeout || 3e4;
  return new Promise((resolve2, reject) => {
    const worker = new Worker(workerCode, {
      eval: true,
      workerData: {
        toolPath: toolUrl,
        callableName,
        args: args || {},
        ctx: sanitizeContext(ctx)
      },
      resourceLimits: {
        maxOldGenerationSizeMb: 256,
        maxYoungGenerationSizeMb: 64
      }
    });
    const timer = setTimeout(() => {
      worker.terminate();
      reject(new Error(`Node tool ${toolName} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    worker.on("message", (msg) => {
      clearTimeout(timer);
      if (msg.error) {
        reject(new Error(msg.error));
      } else {
        resolve2(msg.result);
      }
      worker.terminate();
    });
    worker.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    worker.on("exit", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(new Error(`Node tool ${toolName} exited with code ${code}`));
      }
    });
  });
}
function sanitizeContext(ctx) {
  const allowed = ["page", "browser", "fetch", "cdp", "taskSpaces", "site"];
  const sanitized = {};
  for (const key of allowed) {
    if (ctx && typeof ctx[key] !== "undefined") {
      try {
        sanitized[key] = ctx[key];
      } catch {
      }
    }
  }
  return sanitized;
}
async function loadBrowserToolSource(siteId, toolName, options = {}) {
  const { siteDir, manifest } = await findSiteSkill(siteId, options);
  const schema = toolSchemas(manifest, "browserTools")[toolName];
  if (!schema || typeof schema !== "object") {
    throw new Error(
      `browser tool ${JSON.stringify(toolName)} is not declared by site skill ${JSON.stringify(siteId)}`
    );
  }
  const toolPath = relativeSitePath(siteDir, schema.path, "browser tool");
  return readFile(toolPath, "utf8");
}
function wrapBrowserTool(source, args = {}) {
  return `(async () => { const __egoBrowserTool = ${source}; return await __egoBrowserTool(${JSON.stringify(args || {})}); })()`;
}
function siteSkillNotFoundError(siteId, searchedRoot) {
  const workspace = process.env.EGO_BROWSER_AGENT_WORKSPACE || "unset";
  const lines = [
    `site skill not found: ${JSON.stringify(siteId)}`,
    `  searched: ${searchedRoot}`,
    `  EGO_BROWSER_AGENT_WORKSPACE: ${workspace}`,
    `  hint: ensure your write path begins with the searched root above`
  ];
  return new Error(lines.join("\n"));
}
function toolSchemas(manifest, key) {
  const value = manifest[key] || {};
  return value && typeof value === "object" && !Array.isArray(value) ? { ...value } : {};
}
function relativeSitePath(siteDir, manifestPath, label) {
  if (typeof manifestPath !== "string" || !manifestPath.trim()) {
    throw new Error(`${label} path must be a non-empty relative path`);
  }
  if (manifestPath.includes("\\") || isAbsolute(manifestPath) || manifestPath.split("/").includes("..")) {
    throw new Error(
      `${label} path must be relative to the site skill directory`
    );
  }
  const resolved = resolve(siteDir, manifestPath);
  const siteRoot = resolve(siteDir);
  if (resolved !== siteRoot && !resolved.startsWith(`${siteRoot}/`)) {
    throw new Error(`${label} path must stay inside the site skill directory`);
  }
  return resolved;
}
export {
  checkDomainLearningExists,
  checkLearningExists,
  findSiteSkill,
  iterLearningDirs2 as iterLearningDirs,
  learningEntry,
  learningsRoot2 as learningsRoot,
  loadBrowserToolSource,
  loadLearnedContext,
  pathExists,
  runNodeSiteTool,
  siteSkillsForUrl2 as siteSkillsForUrl,
  siteSkillsRoot2 as siteSkillsRoot,
  validateLearning2 as validateLearning,
  validateLearnings2 as validateLearnings,
  validateSiteSkills2 as validateSiteSkills,
  wrapBrowserTool
};
