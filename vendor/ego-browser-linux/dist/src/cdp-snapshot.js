import { getClient } from "./ws-cdp-client.js";
import { buildEgoError } from "./ego-errors.js";
async function cdpSnapshot(options = {}) {
  const client = await getClient();
  const { ensureSession } = await import("./browser-runtime.js");
  const sessionId = await ensureSession();
  try {
    const rootResult = await client.send(
      "Accessibility.getFullAXTree",
      {},
      sessionId
    );
    const rootNodes = rootResult.result?.nodes || [];
    let childFrames = [];
    try {
      const frameTree = await client.send("DOM.getFrameTree", {}, sessionId);
      childFrames = extractChildFrames(frameTree.result?.frameTree);
    } catch {
    }
    const allNodes = [...rootNodes];
    const allRefs = [];
    for (const frame of childFrames) {
      try {
        const attached = await client.send("Target.attachToTarget", {
          targetId: frame.targetId,
          flatten: true
        });
        const frameSessionId = attached.result?.sessionId || attached.sessionId;
        const frameAxResult = await client.send(
          "Accessibility.getFullAXTree",
          {},
          frameSessionId
        );
        const frameNodes = frameAxResult.result?.nodes || [];
        allNodes.push(...frameNodes);
        await client.send("Target.detachFromTarget", {
          sessionId: frameSessionId
        });
      } catch {
      }
    }
    for (const node of allNodes) {
      if (node.backendDOMNodeId && node.role?.value && node.role.value !== "generic") {
        allRefs.push({
          backendNodeId: node.backendDOMNodeId,
          role: node.role.value,
          name: node.name?.value || ""
        });
      }
    }
    const content = formatAxTree(allNodes, options);
    return { content, refs: allRefs };
  } catch (err) {
    throw buildEgoError(err, "snapshot");
  }
}
function formatAxTree(nodes, options = {}) {
  const nodeMap = /* @__PURE__ */ new Map();
  for (const node of nodes) {
    nodeMap.set(node.nodeId, node);
  }
  const roots = nodes.filter(
    (n) => !n.parentId || !nodeMap.has(n.parentId)
  );
  const lines = [];
  function renderNode(node, depth) {
    const indent = "  ".repeat(depth);
    const role = node.role?.value || "unknown";
    const name = node.name?.value || "";
    const ref = node.backendDOMNodeId ? `[ref=${node.backendDOMNodeId}]` : "";
    if (role === "generic" || role === "none" || role === "InlineTextBox") {
      if (node.childIds) {
        for (const childId of node.childIds) {
          const child = nodeMap.get(childId);
          if (child) renderNode(child, depth);
        }
      }
      return;
    }
    let line = `${indent}- ${role}`;
    if (name) line += ` "${name}"`;
    if (ref) line += ` ${ref}`;
    lines.push(line);
    if (node.childIds) {
      for (const childId of node.childIds) {
        const child = nodeMap.get(childId);
        if (child) renderNode(child, depth + 1);
      }
    }
  }
  for (const root of roots) {
    renderNode(root, 0);
  }
  return lines.join("\n");
}
function extractChildFrames(frameTree) {
  const frames = [];
  if (!frameTree) return frames;
  function walk(node) {
    if (!node) return;
    if (node.frame?.id && node.frame?.id !== frameTree.frame?.id) {
      frames.push({ targetId: node.frame.id, url: node.frame.url });
    }
    if (node.childFrames) {
      for (const child of node.childFrames) {
        walk(child);
      }
    }
  }
  walk(frameTree);
  return frames;
}
export {
  cdpSnapshot
};
