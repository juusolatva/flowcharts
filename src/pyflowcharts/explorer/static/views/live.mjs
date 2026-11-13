// Server-Sent Events: the server announces each new generation; EventSource reconnects by itself.
// A hidden tab closes its stream, because browsers allow only about six HTTP/1.x connections per
// server and every open tab holds one; on becoming visible again the tab reconnects, and the
// generation the server sends on connect triggers a refetch if anything changed meanwhile.
export function startLive({ onGeneration, onStatus }) {
  let source = null;

  function connect() {
    source = new EventSource("/api/events");
    source.addEventListener("generation", (event) => {
      const generation = Number(event.data);
      if (Number.isInteger(generation)) onGeneration(generation);
    });
    source.addEventListener("open", () => onStatus("connected"));
    source.addEventListener("error", () => onStatus("reconnecting"));
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      source?.close();
      source = null;
    } else if (!source) {
      connect();
    }
  });
  if (!document.hidden) connect();
}
