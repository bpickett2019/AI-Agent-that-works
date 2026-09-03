class RefMap {
  map;
  constructor() {
    this.map = /* @__PURE__ */ new Map();
  }
  add(refId, backendNodeId, role, name, nth = void 0) {
    this.addWithFrame(refId, backendNodeId, role, name, nth, void 0);
  }
  addWithFrame(refId, backendNodeId, role, name, nth = void 0, frameId = void 0) {
    this.map.set(refId, {
      backendNodeId,
      role,
      name,
      nth,
      selector: void 0,
      frameId
    });
  }
  get(refId) {
    return this.map.get(refId);
  }
  remove(refId) {
    this.map.delete(refId);
  }
  clear() {
    this.map.clear();
  }
}
function parseRef(input) {
  const trimmed = String(input || "").trim();
  for (const candidate of [
    trimmed.startsWith("@") ? trimmed.slice(1) : null,
    trimmed.startsWith("ref=") ? trimmed.slice(4) : null,
    trimmed
  ]) {
    if (candidate && /^\d+$/.test(candidate)) {
      return candidate;
    }
  }
  return null;
}
export {
  RefMap,
  parseRef
};
