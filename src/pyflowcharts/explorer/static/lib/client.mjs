import { createTracker, isStale } from "./generation.mjs";

export class StaleError extends Error {}

export const isIgnorable = (error) => error?.name === "AbortError" || error instanceof StaleError;

// Every data request carries ?g=<generation>. Accepting a newer generation aborts the requests
// of the older one; a 409 or a newer generation event triggers a single shared refetch.
// A failed state request is retried after RETRY_MS (one pending retry at a time), so the page
// recovers without waiting for the next edit. `fetch` and `schedule` are injectable for tests.
const RETRY_MS = 2000;

export function createApi({
  onState, onBusy, onError, onOk, fetch = globalThis.fetch, schedule = setTimeout,
}) {
  const tracker = createTracker();
  let controller = new AbortController();
  let inflight = null;
  let retrying = false;

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
      if (!retrying) {
        retrying = true;
        schedule(() => {
          retrying = false;
          refresh();
        }, RETRY_MS);
      }
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
