export function createTracker() {
  let current = null;
  return {
    get current() {
      return current;
    },
    needsRefetch: (generation) => generation !== current,
    set(generation) {
      current = generation;
    },
  };
}

export function isStale(status) {
  return status === 409;
}
