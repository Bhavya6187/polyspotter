const _PLUGINS = new Map();

export function register(sportId, slots) {
  if (!slots || typeof slots !== "object") {
    throw new Error(`register(${sportId}): slots must be an object`);
  }
  if (!slots.Banner) {
    throw new Error(`register(${sportId}): Banner is required`);
  }
  _PLUGINS.set(sportId, {
    Banner: slots.Banner,
    Header: slots.Header || null,
    Sidebar: slots.Sidebar || null,
  });
}

export function getPlugin(sportId) {
  return _PLUGINS.get(sportId) || null;
}

export function allSportIds() {
  return Array.from(_PLUGINS.keys());
}
