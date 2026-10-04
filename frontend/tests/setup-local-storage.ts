// Node 26 ships an experimental global `localStorage` that is `undefined` unless Node is started
// with --localstorage-file. Vitest's jsdom environment does not override that global, so
// `window.localStorage` is `undefined` there. Install an in-memory Storage when it is missing so
// the suite does not depend on the Node version.
function createInMemoryStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    get length() {
      return entries.size;
    },
    clear: () => entries.clear(),
    getItem: (key) => entries.get(key) ?? null,
    key: (index) => Array.from(entries.keys())[index] ?? null,
    removeItem: (key) => {
      entries.delete(key);
    },
    setItem: (key, value) => {
      entries.set(key, String(value));
    }
  };
}

if (!window.localStorage) {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: createInMemoryStorage()
  });
}
