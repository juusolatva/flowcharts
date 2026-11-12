# Exception edges and `return`/`raise` through `finally`: design

Status: approved in brainstorming on 2026-11-13. Extends `2026-11-11-python-flowcharts-design.md` (the "main spec"). Where they disagree, this document wins, and the last implementation step folds it into the main spec.

## Goal

Remove two known simplifications of the chart builder:

1. Exception edges start at the `try` node. They should start at each statement that can raise.
2. `return` and `raise` inside `try … finally` go straight to `end`. They should run the finally body first, as `break`/`continue` already do.

Success means every path a `return`, `raise` or raising statement can take through its enclosing `try` blocks is drawn, under one documented assumption (handlers catch what reaches them), and charts stay deterministic with unique node IDs.

## Decisions

| Question | Decision |
|---|---|
| Which nodes get exception edges | Every node created inside a `try` body, including decision and loop nodes and nodes nested in them. Any statement can raise (comparisons, iteration, attribute access), and a heuristic would be language-specific and could hide a real path. |
| Fan-out | Direct edges: each node gets one `exception` edge per handler. No junction node. The density is accepted; backends draw exception edges dashed, and the GUI can hide them. |
| The `try` node | Gets no exception edges. Entering a `try` cannot raise. The `try → handler` edges of today are removed. |
| Unmatched handlers | Not drawn. A handler is assumed to catch whatever reaches it. The uncaught path out of a `try` that has handlers is not drawn. |
| `raise` | An ordinary raising node. Inside a `try` it gets the same exception edges as every other node and no direct edge to `end`. Outside any `try` it goes to `end`, as today. |
| `return` | Runs a `finally (return)` copy of each enclosing finally body, then goes to `end`. |
| IR | No change. The edge label `exception` and the `~finally` suffix already exist. No `SCHEMA_VERSION` bump. |
| Scope | Only the CFG items. Module-level code, directory recursion and call graphs stay out of scope. |

## Exception scopes

The builder keeps a stack of *exception scopes*. When a node is added while a scope is active, the node also gets an `exception` edge to each of the scope's targets. `emit_try` pushes the scopes:

- **The `try` body.** Targets are the handler nodes. A `try` with no handlers has a `finally` (Python requires one or the other), and the target is then a pending frontier that later feeds the `finally (exception)` copy.
- **The `else` body and each handler body.** If the `try` has a `finally`, the target is that pending `finally (exception)` frontier. Otherwise no scope is pushed, so these nodes inherit the enclosing `try`'s targets: an exception that escapes a handler propagates outward.
- **Outside any `try`.** No scope, no exception edges. Propagation to `end` stays implicit.

The `try` node itself is created before its body scope is pushed, so it carries only the enclosing scope's edges. A `try` whose body produces no nodes (`try: pass`) leaves its handlers without incoming edges, the same as unreachable code today.

Handler nodes are created after the handler scope is pushed, so a handler node itself points at the `finally (exception)` copy or the outer handlers. This is how a re-raise in a handler, or a handler whose own body raises, flows outward.

Nested `try` inside a `try` body: inner body nodes point only at the inner handlers (assumed to catch). Inner handler nodes and their bodies point at the inner `finally (exception)` copy if there is one, else at the outer handlers.

## Finally copies

Today a finally body is drawn once per path that runs it: `finally`, `finally (break)`, `finally (continue)`. Two copies are added, built with the same machinery (a pending frontier collected while the `try` is open, a copy drawn when it closes, and the copy's exit routed onward):

- **`finally (return)`** collects the `return` nodes inside the `try`, at any loop depth (unlike `break`/`continue`, which only pass through a `finally` inside their loop). Its exit routes to the next enclosing pending `finally`, else to `end`.
- **`finally (exception)`** collects the pending exception frontier described above. Its exit routes to the enclosing exception scope's targets as `exception` edges (the exit frontier's own labels are dropped, and a node that already has an `exception` edge to that target gets no second one), else to `end` with the frontier's own labels. The copy is only created when at least one edge points at it.

A finally body that ends the path itself (its own `return`, `raise`, `break` or `continue`) still overrides the pending transfer, as today.

Node IDs: the copy suffixes `~return@L{line}C{col}` and `~exception@L{line}C{col}` name the owning `try`, alongside the existing `~break@…` and `~continue@…`. The copy's finally node is `{try_id}~finally{copy suffix}`.

## Worked example

```python
def f(path):
    try:
        data = load(path)        # L3
        return parse(data)       # L4
    except OSError:              # L5
        log()                    # L6
        raise                    # L7
    finally:
        close(path)              # L9
```

Edges (labels in brackets, exception edges dashed in the backends):

- `start → try → load(path) → return parse(data)`
- `load(path) → except OSError [exception]`, `return parse(data) → except OSError [exception]`
- `return parse(data) → finally (return) → close(path) → end`
- `except OSError → finally (exception) [exception]`, `log() → finally (exception) [exception]`, `raise → finally (exception) [exception]`
- `except OSError → log() → raise`
- `finally (exception) → close(path) → end`

No path completes the `try` normally here, so the plain `finally` copy is omitted. This is a small behaviour change: today the plain copy is always drawn, even with no incoming edges. From now on every finally copy (`finally`, `finally (break)`, `finally (continue)`, `finally (return)`, `finally (exception)`) is drawn only when at least one edge points at it.

## Backends

The DOT and Mermaid backends draw edges labelled `exception` dashed (`style=dashed` in DOT, `-.->` in Mermaid). Nothing else changes. JSON is unaffected.

## Documentation

- Main spec: rewrite the `try` bullet under "Node kinds and shapes" and replace the two entries under "Known simplifications" with: handlers are assumed to catch, so the uncaught path out of a `try` with handlers is not drawn; and the `try` node itself has no exception edges. Add the two new copy suffixes to the "Stable node IDs" rule.
- `AGENTS.md`: same replacement under "Known simplifications", and the new suffixes in the node ID rule.

## Testing

Test-driven, asserting on `flow(chart)` triples:

- Per-statement edges with one and with two handlers; the `try` node has none.
- Nested `try`: inner body nodes point only at inner handlers; inner handler nodes point at outer handlers (no inner `finally`) or at the inner `finally (exception)` (with one).
- `raise` in a `try` body, in a handler, in a `try` without handlers, and outside any `try`.
- `return` through one `finally`, through two nested `finally` blocks, and inside a loop inside `try … finally`.
- `finally (exception)` exit chaining to outer handlers, and to `end` at top level.
- A finally body that ends the path overrides the pending `return`.
- `try: pass` leaves handlers unreachable without error.
- Existing assertions of `("try", "except …", "exception")` are updated.
- The invariants corpus gains these shapes (unique IDs, every edge endpoint exists, deterministic output).
- DOT and Mermaid tests check the dashed style on exception edges only.
