import { createDragTracker } from "../lib/drag.mjs";

const DRAG_THRESHOLD = 4;
const WHEEL_STEP = 1.15;

// Pan and zoom by editing the SVG's viewBox. A drag of more than DRAG_THRESHOLD px suppresses
// the click that follows it (the flag is cleared by that click or the next pointerdown).
export function attachPanZoom(svg) {
  const home = svg.viewBox.baseVal;
  const initial = [home.x, home.y, home.width, home.height];
  let suppress = false;
  const drag = createDragTracker(DRAG_THRESHOLD);

  const toUser = (clientX, clientY) =>
    new DOMPoint(clientX, clientY).matrixTransform(svg.getScreenCTM().inverse());

  function zoomAt(factor, point) {
    const box = svg.viewBox.baseVal;
    const p = point ?? { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    box.x = p.x - (p.x - box.x) / factor;
    box.y = p.y - (p.y - box.y) / factor;
    box.width /= factor;
    box.height /= factor;
  }

  svg.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      zoomAt(event.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP, toUser(event.clientX, event.clientY));
    },
    { passive: false },
  );

  let pointer = null; // only the first pointer pans; a second finger is ignored

  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || pointer !== null) return;
    pointer = event.pointerId;
    suppress = false;
    drag.begin(event.clientX, event.clientY);
    const move = (e) => {
      if (e.pointerId !== pointer) return;
      const delta = drag.move(e.clientX, e.clientY);
      if (!delta) return;
      suppress = true;
      const scale = svg.getScreenCTM().a;
      const box = svg.viewBox.baseVal;
      box.x -= delta.dx / scale;
      box.y -= delta.dy / scale;
    };
    const up = (e) => {
      if (e.pointerId !== pointer) return;
      pointer = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  });

  // on the svg itself, so a stale flag dies with the svg when the stage is re-rendered
  for (const type of ["click", "dblclick"]) {
    svg.addEventListener(
      type,
      (event) => {
        if (!suppress) return;
        if (type === "click") suppress = false;
        event.stopImmediatePropagation();
        event.preventDefault();
      },
      true,
    );
  }

  return {
    fit() {
      const box = svg.viewBox.baseVal;
      [box.x, box.y, box.width, box.height] = initial;
    },
    zoom: (factor) => zoomAt(factor, null),
  };
}
