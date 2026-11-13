import { createTracker, isStale } from "./generation.mjs";

export class StaleError extends Error {}

export const isIgnorable = (error) => error?.name === "AbortError" || error instanceof StaleError;

// Every data request carries ?g=<generation>. Accepting a newer generation aborts the requests
// of the older one; a 409 or a newer generation event triggers a single shared refetch.
// `fetch` is injectable for tests.
export function createApi({ onState, onBusy, onError, onOk, fetch = globalThis.fetch }) {
  const tracker = createTracker();
  let controller = new AbortController();
  let inflight = null;

  async function fetchState() {
    onBusy(true);
    try {
      const response = await fetch("/api/state");
      if (!response.ok) throw new Error(`/api/state: HTTP ${response.status}`);
      const state = await response.json();
      onOk();
      if (tracker.needsRefetch(state.generation)) {
        controller.abort();
        controller = new AbortController();
        tracker.set(state.generation);
        onState(state);
      }
    } catch (error) {
      onError(error);
    } finally {
      inflight = null;
      onBusy(false);
    }
  }

  function refresh() {
    inflight ??= fetchState();
    return inflight;
  }

  async function noteGeneration(generation) {
    if (!tracker.needsRefetch(generation)) return;
    await refresh();
    // the shared fetch may have started before this generation existed
    if (generation > (tracker.current ?? -1)) await refresh();
  }

  async function request(path) {
    const response = await fetch(`${path}?g=${tracker.current}`, { signal: controller.signal });
    if (isStale(response.status)) {
      refresh();
      throw new StaleError("stale generation");
    }
    if (!response.ok) {
      throw new Error((await response.text()).trim() || `HTTP ${response.status}`);
    }
    return response;
  }

  return {
    refresh,
    noteGeneration,
    text: async (path) => (await request(path)).text(),
    json: async (path) => (await request(path)).json(),
  };
}
