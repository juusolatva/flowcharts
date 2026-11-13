// "/" focuses the search box, unless the user is typing or holds a modifier.
export function opensSearch(event) {
  if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return false;
  const target = event.target;
  if (target?.isContentEditable) return false;
  return !["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName);
}
