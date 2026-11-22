# Desktop engine protocol v1

The native GUI launches an engine executable and exchanges **UTF-8 JSON objects, one per line**,
over stdin/stdout. There is no network transport or frontend-language binding. stdout is
reserved for protocol messages; diagnostic logging belongs on stderr. EOF requests shutdown.
The initial implementation is `uv run python -P -u -m pyflowcharts.desktop`, started in the
flowcharts checkout.

The protocol is intentionally separate from the stable IR JSON schema. Changing the transport
does not change `Document` or `SCHEMA_VERSION`. Documents inside snapshots retain their normal
IR JSON representation (currently version 3). A future C++ engine must implement the same
semantic contract or negotiate a new protocol version; the GUI must not infer a language from
how the worker was built.

## Envelope

Request:

```json
{"protocol_version":1,"id":1,"method":"open","params":{"paths":["/project/src"]}}
```

Success:

```json
{"protocol_version":1,"id":1,"ok":true,"result":{"snapshot":{}}}
```

Error:

```json
{"protocol_version":1,"id":1,"ok":false,"error":{"code":"invalid_request","message":"Explanation"}}
```

`id` is a non-negative integer no greater than 2^53 - 1. It is echoed by the engine; malformed
requests without a usable ID receive `null`. Booleans are not integers. Unsupported protocol
versions receive `unsupported_protocol`, not a best-effort interpretation.

The GUI sends one request at a time. Waiting graph requests are coalesced so rapid navigation
does not queue every intermediate layout. Opening a new workspace discards waiting requests
for the old one. In-flight work can complete, but stale UI requests are ignored by ID. Normal
engine errors do not close the session; malformed responses, process failure and the client
watchdog disconnect it and show a diagnostic. The watchdog covers engine startup and `graph`
requests (120 seconds; layout itself is limited to 30 seconds by the engine). `open` and
`refresh` have no client deadline, since analysing a large workspace takes as long as it takes.
A `refresh` failure that repeats on every poll is reported once, until a refresh succeeds or
the message changes.

The worker accepts requests of up to 1 MiB, not counting the newline; the client accepts response frames up to 512 MiB. These
are per-frame limits, not per-read limits. Neither endpoint assumes a pipe read equals a frame.
Invalid UTF-8, malformed JSON and oversized request frames receive `invalid_request` with a null
ID; the worker discards only that frame and continues processing subsequent requests. That
includes JSON nested too deeply for the decoder. An unexpected failure while handling a request
(for example an `OSError` while re-scanning a directory) receives `internal_error` with the
request's ID, and the session stays open. The worker writes the traceback to stderr.

Responses are UTF-8. A file name whose bytes are not valid in the file-system encoding reaches
the worker as lone surrogates (Python's `surrogateescape`); those are written as JSON `\uDCxx`
escapes, so the frame stays valid UTF-8.

Because the GUI has at most one request in flight, it treats a null-ID error as the failure of
that request (for example an `open` with more paths than fit in 1 MiB) and keeps the session.

## Methods

### `open`

Parameters: `paths`, a non-empty array of non-empty file/directory path strings. Relative paths
are relative to the worker's working directory; the GUI sends absolute paths. Opening replaces
the workspace and layout cache. Invalid paths and syntax errors are represented as workspace
diagnostics, not transport failure, so partial/empty workspaces can still be explored.

Result: `{ "snapshot": SNAPSHOT }`.

The current adapter uses default chart options and no exclusions. Optional chart settings can
be added deliberately in a later protocol revision; they are not silently accepted today.

### `refresh`

No parameters. Re-scan the open workspace using the existing watcher/settle rules. The GUI
polls once a second while the engine is idle; parsing never runs on the UI thread.

Result: `{ "changed": false }`, or `{ "changed": true, "snapshot": SNAPSHOT }`.
A changed snapshot increments the generation and invalidates all cached layouts. Opening
another workspace starts at generation 1 again, so response IDs are also important: generation
alone is not a workspace identifier.

### `graph`

For a function/module chart:

```json
{"generation":1,"document":0,"qualname":"Inventory.load"}
```

For the run's call graph:

```json
{"generation":1,"document":null}
```

`generation` must match the current workspace. The call graph takes no `qualname` (omit it or
send `null`). The module qualname is `<module>`. Document
indexes refer only to that snapshot. Result:

```json
{"generation":1,"layout":{"bb":"0,0,100,100","objects":[],"edges":[]}}
```

`layout` is Graphviz `dot -Tjson` output, including drawing operations; it is **not IR JSON**.
Node `name` identifies the semantic node. Call-graph nodes retain the existing DOT backend's
`documentIndex#qualname` names. Node/edge paths, labels and clusters are decoded into native Qt
scene items. Graphviz's upward Y coordinates become negative Qt Y coordinates, so graph bounds
may be negative. No layout fields are added to semantic documents.

Layout is cached per chart until the workspace changes. The worker invokes `dot` without a
shell and with a 30-second timeout. `layout_error` reports missing Graphviz, failed layout,
timeout or invalid output; failed layouts are not cached.

Other errors: `no_workspace`, `unknown_method`, `not_found`, `stale_generation`,
`internal_error`.

## Snapshot

The explorer's existing `snapshot_json` fields are reused: `generation`, `entries`, `messages`
and `edges`. One additional **transport** field, `documents`, carries the engine-decoded source
along with each semantic document:

```json
{
  "generation":1,
  "entries":[],
  "messages":[],
  "edges":[],
  "documents":[
    {"document":{"schema_version":3,"source":"/project/a.py","language":"python","module_name":"a","functions":[],"module":null},
     "source_text":"# decoded by the language frontend\n"}
  ]
}
```

The GUI never reopens/redecodes source files. Entry `doc` indexes this array. Stable chart
identity across snapshots is `(source path, qualname)`, not the document index; source node IDs
retain the existing IR identity rules. Layout and view state remain outside the semantic IR.
