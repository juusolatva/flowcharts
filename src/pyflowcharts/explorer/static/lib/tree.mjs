// Folder tree for the sidebar: folders come from the key's segments, each file's leaf label is
// the source file name (so "io.py", not "io").
const baseName = (source) => source.split(/[\\/]/).pop();

export function buildTree(entries) {
  const root = { name: "", path: "", folders: [], files: [] };
  for (const entry of entries) {
    const segments = entry.key.split("/");
    let node = root;
    segments.slice(0, -1).forEach((name, i) => {
      let child = node.folders.find((f) => f.name === name);
      if (!child) {
        child = { name, path: segments.slice(0, i + 1).join("/"), folders: [], files: [] };
        node.folders.push(child);
      }
      node = child;
    });
    node.files.push({ label: baseName(entry.source), entry });
  }
  return root;
}
