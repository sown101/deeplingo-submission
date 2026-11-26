import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { useContainer } from "../../../app/container";
import type { WordImage } from "../notebookApi";
import { chunks } from "./model";

const BATCH = 24;

/**
 * Pictures for the words on screen, asked for at most 24 at a time as tiles scroll into view.
 * A word maps to null once the server has answered that it has no picture.
 */
export function useWordImages(active: boolean, shown: readonly string[], grid: RefObject<HTMLElement | null>) {
  const { notebook } = useContainer();
  const [images, setImages] = useState<Record<string, WordImage | null>>({});
  const requested = useRef(new Set<string>());

  const request = useCallback((ids: string[]) => {
    for (const batch of chunks(ids.filter(id => !requested.current.has(id)), BATCH)) {
      batch.forEach(id => requested.current.add(id));
      notebook.images(batch).then(found => setImages(current => {
        const next = { ...current };
        for (const id of batch) next[id] = found.find(image => image.conceptId === id) ?? null;
        return next;
      })).catch(() => batch.forEach(id => requested.current.delete(id))); // Tiles keep their colour block.
    }
  }, [notebook]);

  const shownKey = shown.join(",");
  useEffect(() => {
    if (!active || !shownKey) return;
    const ids = shownKey.split(",");
    if (typeof IntersectionObserver === "undefined") { request(ids); return; }
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting)
        .map(entry => ids.indexOf((entry.target as HTMLElement).dataset.conceptId ?? ""))
        .filter(index => index >= 0)
        .sort((a, b) => a - b);
      for (const index of visible) {
        if (!requested.current.has(ids[index])) request(ids.slice(index).filter(id => !requested.current.has(id)).slice(0, BATCH));
      }
    }, { rootMargin: "400px" });
    grid.current?.querySelectorAll("[data-concept-id]").forEach(tile => observer.observe(tile));
    return () => observer.disconnect();
  }, [active, shownKey, grid, request]);

  const putImage = useCallback((conceptId: string, image: WordImage | null) => {
    setImages(current => ({ ...current, [conceptId]: image }));
  }, []);

  return { images, putImage };
}
