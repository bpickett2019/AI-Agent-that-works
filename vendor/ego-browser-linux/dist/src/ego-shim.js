import { getClient } from "./ws-cdp-client.js";
import { cdpSnapshot } from "./cdp-snapshot.js";
const taskSpaces = /* @__PURE__ */ new Map();
let nextSpaceId = 1;
let activeSpaceId = null;
function normalizeSpace(space) {
  return {
    taskId: space.taskId,
    id: space.id,
    name: space.name,
    ownership: space.ownership,
    recentTabTitles: space.recentTabTitles || []
  };
}
const egoShim = {
  // ─── Tab/CDP operations ───────────────────────────────────
  async listTabs() {
    const client = await getClient();
    const result = await client.send("Target.getTargets");
    const targets = (result.result?.targetInfos || []).filter(
      (t) => t.type === "page"
    );
    return {
      tabs: targets.map((t) => ({
        targetId: t.targetId,
        title: t.title || "",
        url: t.url || "",
        active: t.active || false
      }))
    };
  },
  async createTab(url) {
    const client = await getClient();
    const result = await client.send("Target.createTarget", { url });
    return { targetId: result.result?.targetId };
  },
  async snapshot(options) {
    return cdpSnapshot(options || {});
  },
  // ─── Task Spaces ──────────────────────────────────────────
  async listTaskSpaces() {
    const client = await getClient();
    const result = await client.send("Target.getTargets");
    const targets = (result.result?.targetInfos || []).filter(
      (t) => t.type === "page"
    );
    const spaces = [...taskSpaces.values()].map(normalizeSpace);
    for (const target of targets) {
      const tracked = [...taskSpaces.values()].find(
        (s) => s.targetId === target.targetId
      );
      if (!tracked) {
        const id = nextSpaceId++;
        const space = {
          taskId: `ts-${id}`,
          id,
          name: target.title || `Tab ${id}`,
          ownership: "user",
          targetId: target.targetId,
          recentTabTitles: [target.title || target.url || ""]
        };
        taskSpaces.set(id, space);
        spaces.push(normalizeSpace(space));
      }
    }
    return { taskSpaces: spaces };
  },
  async createTaskSpace(name) {
    const client = await getClient();
    const result = await client.send("Target.createTarget", {
      url: "about:blank"
    });
    const targetId = result.result?.targetId;
    const id = nextSpaceId++;
    const space = {
      taskId: `ts-${id}`,
      id,
      name: name || `Task ${id}`,
      ownership: "agent",
      targetId,
      recentTabTitles: []
    };
    taskSpaces.set(id, space);
    activeSpaceId = id;
    return normalizeSpace(space);
  },
  async useTaskSpace(id) {
    const space = taskSpaces.get(id);
    if (!space) {
      throw new Error(`Task space not found: ${id}`);
    }
    activeSpaceId = id;
    if (space.targetId) {
      const client = await getClient();
      await client.send("Target.activateTarget", {
        targetId: space.targetId
      });
    }
    return normalizeSpace(space);
  },
  async claimTaskSpace(id, name) {
    const space = taskSpaces.get(id);
    if (!space) {
      throw new Error(`Task space not found: ${id}`);
    }
    space.ownership = "agent";
    activeSpaceId = id;
    return normalizeSpace(space);
  },
  async completeTaskSpace() {
    if (activeSpaceId !== null) {
      const space = taskSpaces.get(activeSpaceId);
      if (space) {
        space.ownership = "agentDelegatedToUser";
      }
    }
    return { done: true };
  },
  async closeTaskSpace() {
    if (activeSpaceId !== null) {
      const space = taskSpaces.get(activeSpaceId);
      if (space?.targetId) {
        const client = await getClient();
        await client.send("Target.closeTarget", {
          targetId: space.targetId
        });
      }
      taskSpaces.delete(activeSpaceId);
      activeSpaceId = null;
    }
    return { done: true };
  },
  async handOffTaskSpace() {
    if (activeSpaceId !== null) {
      const space = taskSpaces.get(activeSpaceId);
      if (space) {
        space.ownership = "agentDelegatedToUser";
      }
    }
    return { done: true };
  },
  async takeOverTaskSpace() {
    if (activeSpaceId !== null) {
      const space = taskSpaces.get(activeSpaceId);
      if (space) {
        space.ownership = "agent";
      }
    }
    return { done: true };
  },
  // ─── CDP passthrough ──────────────────────────────────────
  onCDPMessage: null,
  onSendCDPMessageError: null,
  sendCDPMessage(payload) {
    throw new Error(
      "egoShim.sendCDPMessage is not used \u2014 browser-runtime.ts uses CdpWebSocketClient directly"
    );
  }
};
function installEgoShim() {
  if (!globalThis.ego) {
    globalThis.ego = egoShim;
  }
}
export {
  egoShim,
  installEgoShim
};
