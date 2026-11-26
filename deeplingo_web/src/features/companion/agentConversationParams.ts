import type { CompanionEntry } from "./companionModels";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The conversation an agent link asks for; a malformed link is refused before anything starts. */
export function entryFrom(params: URLSearchParams): { entry: CompanionEntry; item: string | null } | null {
  const entry = params.get("entry") ?? "home";
  if (entry === "video") {
    const item = params.get("item") ?? "";
    return UUID_RE.test(item) ? { entry, item } : null;
  }
  return entry === "home" || entry === "review" ? { entry, item: null } : null;
}

/** Selectors survive moving from Tata's panel to its full conversation. */
export function agentConversationParams(pathname: string, search: string, segmentId?: string | null, topicId?: string) {
  const current = new URLSearchParams(search);
  const item = pathname.match(/^\/library\/videos\/([0-9a-f-]{36})(?:\/|$)/i)?.[1];
  const entry = item ? "video" : pathname.startsWith("/review") ? "review" : "home";
  const params = new URLSearchParams({ mode: "voice", entry });
  for (const key of ["practice", "scenario", "swap"]) {
    const value = current.get(key);
    if (value !== null) params.set(key, value);
  }
  if (item) {
    params.set("item", item);
    const segment = segmentId ?? current.get("segment");
    if (segment) params.set("segment", segment);
  } else if (entry === "home") {
    const notebook = pathname.match(/^\/words\/lists\/([0-9a-f-]{36})(?:\/|$)/i)?.[1];
    const topic = topicId ?? current.get("topic") ?? notebook;
    if (topic) params.set("topic", topic);
  }
  return params;
}
