import { sourceLines } from "../lib/sourcemap.mjs";
import { el, link } from "./dom.mjs";

// The source pane: numbered lines (textContent only), a highlighted range, a "go to" hint.
export function createSource({ lines, title, hint, toggle, layout, onLine }) {
  let rows = [];
  let marked = [];

  lines.addEventListener("click", (event) => {
    const row = event.target.closest(".line");
    if (row) onLine(Number(row.dataset.line));
  });
  toggle.addEventListener("click", () => {
    const collapsed = layout.classList.toggle("source-collapsed");
    toggle.textContent = collapsed ? "‹" : "›";
  });

  function clearHint() {
    hint.replaceChildren();
  }

  return {
    clearHint,
    clear(message) {
      rows = [];
      marked = [];
      title.textContent = "";
      clearHint();
      lines.replaceChildren(el("p", { class: "muted", text: message }));
    },
    show(label, text) {
      title.textContent = label;
      clearHint();
      rows = sourceLines(text).map((code, i) =>
        el("div", { class: "line", "data-line": String(i + 1) },
          el("span", { class: "num", text: String(i + 1) }),
          el("span", { class: "code", text: code })),
      );
      marked = [];
      lines.replaceChildren(...rows);
    },
    highlight(start, end) {
      for (const row of marked) row.classList.remove("hl");
      marked = rows.slice(Math.max(start - 1, 0), end);
      for (const row of marked) row.classList.add("hl");
      marked[0]?.scrollIntoView({ block: "nearest" });
    },
    unhighlight() {
      for (const row of marked) row.classList.remove("hl");
      marked = [];
    },
    showHint(text, href) {
      hint.replaceChildren(link(text, href));
    },
  };
}
