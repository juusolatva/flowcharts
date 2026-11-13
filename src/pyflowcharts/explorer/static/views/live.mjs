// Server-Sent Events: the server announces each new generation; EventSource reconnects by itself.
export function startLive({ onGeneration, onStatus }) {
  const source = new EventSource("/api/events");
  source.addEventListener("generation", (event) => {
    const generation = Number(event.data);
    if (Number.isInteger(generation)) onGeneration(generation);
  });
  source.addEventListener("open", () => onStatus("connected"));
  source.addEventListener("error", () => onStatus("reconnecting"));
  return source;
}
