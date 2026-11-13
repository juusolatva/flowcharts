import assert from "node:assert/strict";
import { test } from "node:test";

import { StaleError, createApi, isIgnorable } from "../../src/pyflowcharts/explorer/static/lib/client.mjs";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

// A fetch whose responses the test releases one at a time.
function scriptedFetch() {
  const calls = [];
  const fetch = (url, options = {}) =>
    new Promise((resolve, reject) => calls.push({ url, signal: options.signal, resolve, reject }));
  return { fetch, calls };
}

function client(fetch) {
  const log = { states: [], errors: [], busy: [], ok: 0 };
  const api = createApi({
    fetch,
    onState: (s) => log.states.push(s.generation),
    onError: (e) => log.errors.push(e.message),
    onBusy: (b) => log.busy.push(b),
    onOk: () => { log.ok += 1; },
  });
  return { api, log };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("concurrent refreshes share one state request", async () => {
  const { fetch, calls } = scriptedFetch();
  const { api, log } = client(fetch);
  const a = api.refresh();
  const b = api.refresh();
  assert.equal(a, b);
  assert.equal(calls.length, 1);
  calls[0].resolve(json({ generation: 1 }));
  await a;
  assert.deepEqual(log.states, [1]);
  assert.deepEqual(log.busy, [true, false]);
  assert.equal(log.ok, 1);
});

test("an unchanged generation is not delivered again", async () => {
  const fetch = async () => json({ generation: 3 });
  const { api, log } = client(fetch);
  await api.refresh();
  await api.refresh();
  assert.deepEqual(log.states, [3]);
});

test("a generation event equal to the current one fetches nothing", async () => {
  let count = 0;
  const { api } = client(async () => { count += 1; return json({ generation: 2 }); });
  await api.refresh();
  await api.noteGeneration(2);
  assert.equal(count, 1);
});

test("a newer event during an older fetch triggers a second fetch", async () => {
  const { fetch, calls } = scriptedFetch();
  const { api, log } = client(fetch);
  const noted = api.noteGeneration(2);
  await tick();
  calls[0].resolve(json({ generation: 1 })); // started before generation 2 existed
  await tick();
  assert.equal(calls.length, 2);
  calls[1].resolve(json({ generation: 2 }));
  await noted;
  assert.deepEqual(log.states, [1, 2]);
});

test("data requests carry the generation and are aborted by a newer one", async () => {
  const { fetch, calls } = scriptedFetch();
  const { api } = client(fetch);
  const first = api.refresh();
  calls[0].resolve(json({ generation: 1 }));
  await first;
  const pending = api.text("/api/source/0");
  assert.equal(calls[1].url, "/api/source/0?g=1");
  const second = api.refresh();
  calls[2].resolve(json({ generation: 2 }));
  await second;
  assert.equal(calls[1].signal.aborted, true);
  calls[1].resolve(new Response("late"));
  assert.equal(await pending, "late"); // the fake fetch ignores the signal; the flag is what counts
});

test("a 409 throws a stale error and refetches the state", async () => {
  const urls = [];
  let generation = 1;
  const fetch = async (url) => {
    urls.push(url);
    if (url === "/api/state") return json({ generation: generation++ });
    return new Response("Conflict\n", { status: 409 });
  };
  const { api, log } = client(fetch);
  await api.refresh();
  await assert.rejects(api.json("/api/document/0"), (e) => e instanceof StaleError && isIgnorable(e));
  await tick();
  assert.deepEqual(urls, ["/api/state", "/api/document/0?g=1", "/api/state"]);
  assert.deepEqual(log.states, [1, 2]);
});

test("other failures carry the server's message", async () => {
  const fetch = async (url) =>
    url === "/api/state" ? json({ generation: 1 }) : new Response("dot exited with status 1\n", { status: 500 });
  const { api } = client(fetch);
  await api.refresh();
  await assert.rejects(api.text("/api/svg/callgraph"), { message: "dot exited with status 1" });
});

test("a failed state request is reported and ends the busy state", async () => {
  const { api, log } = client(async () => new Response("", { status: 403 }));
  await api.refresh();
  assert.deepEqual(log.errors, ["/api/state: HTTP 403"]);
  assert.deepEqual(log.busy, [true, false]);
  assert.equal(log.ok, 0);
});

test("abort errors are ignorable, other errors are not", () => {
  assert.equal(isIgnorable({ name: "AbortError" }), true);
  assert.equal(isIgnorable(new Error("x")), false);
});
