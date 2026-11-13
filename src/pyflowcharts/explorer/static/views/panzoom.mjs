const DRAG_THRESHOLD = 4;
const WHEEL_STEP = 1.15;

// Pan and zoom by editing the SVG's viewBox. A drag of more than DRAG_THRESHOLD px suppresses
// the click/dblclick that follows it (the flag is cleared by the next pointerdown).
export function attachPanZoom(container, svg) {
  const home = svg.viewBox.baseVal;
  const initial = [home.x, home.y, home.width, home.height];
  let suppress = false;

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

  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    suppress = false;
    let last = { x: event.clientX, y: event.clientY };
    const start = { ...last };
    const move = (e) => {
      if (!suppress && Math.hypot(e.clientX - start.x, e.clientY - start.y) <= DRAG_THRESHOLD) return;
      suppress = true;
      const scale = svg.getScreenCTM().a;
      const box = svg.viewBox.baseVal;
      box.x -= (e.clientX - last.x) / scale;
      box.y -= (e.clientY - last.y) / scale;
      last = { x: e.clientX, y: e.clientY };
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  });

  for (const type of ["click", "dblclick"]) {
    container.addEventListener(
      type,
      (event) => {
        if (!suppress) return;
        event.stopPropagation();
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
