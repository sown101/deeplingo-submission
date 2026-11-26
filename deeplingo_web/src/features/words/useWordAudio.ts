import { useCallback, useEffect, useRef, useState } from "react";
import { useContainer } from "../../app/container";

/**
 * Plays a word read aloud. One word at a time; `playing` names the word being read. The dictionary's audio comes first;
 * a saved word the dictionary does not hold (`conceptId` given) is read by its id instead, so every saved word has audio.
 */
export function useWordAudio() {
  const { notebook, review } = useContainer();
  const audio = useRef<HTMLAudioElement | null>(null);
  const urls = useRef(new Map<string, string>());
  const [playing, setPlaying] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => () => {
    audio.current?.pause();
    urls.current.forEach(url => URL.revokeObjectURL(url));
  }, []);

  const play = useCallback(async (languageCode: string, text: string, rate = 1, conceptId?: string) => {
    setFailed(false);
    setPlaying(text);
    try {
      const key = `${languageCode}:${text}`;
      const url = urls.current.get(key) ?? await notebook.audioUrl(languageCode, text).catch((cause: unknown) => {
        if (!conceptId) throw cause;
        return review.audioUrl(conceptId);
      });
      urls.current.set(key, url);
      audio.current?.pause();
      const element = new Audio(url);
      element.playbackRate = rate;
      element.onended = () => setPlaying(null);
      audio.current = element;
      await element.play();
    } catch {
      setPlaying(null);
      setFailed(true);
    }
  }, [notebook, review]);

  return { play, playing, failed };
}
