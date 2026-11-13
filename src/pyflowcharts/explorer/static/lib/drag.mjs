// Decides when a pointer movement becomes a drag: once it strays more than `threshold` px from
// where it started. After that every move reports the delta since the previous one.
export function createDragTracker(threshold) {
  let start = null;
  let last = null;
  let dragging = false;
  return {
    get dragging() {
      return dragging;
    },
    begin(x, y) {
      start = last = { x, y };
      dragging = false;
    },
    move(x, y) {
      if (!start) return null;
      if (!dragging && Math.hypot(x - start.x, y - start.y) <= threshold) return null;
      dragging = true;
      const delta = { dx: x - last.x, dy: y - last.y };
      last = { x, y };
      return delta;
    },
  };
}
