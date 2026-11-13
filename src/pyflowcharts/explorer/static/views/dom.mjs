// Tiny element builder. Text only ever goes through textContent.
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (name === "class") node.className = value;
    else if (name === "text") node.textContent = value;
    else if (/^on[a-z]+$/.test(name) && typeof value === "function") node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value);
  }
  node.append(...children);
  return node;
}

export function link(text, href, props = {}) {
  return el("a", { href, text, ...props });
}
