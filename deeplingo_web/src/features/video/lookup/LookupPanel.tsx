import { useState } from "react";
import type { TranscriptSegmentView } from "../../../lib/api/dto";
import { ConceptSheet } from "../../concept/ConceptSheet";
import { LookupSheet } from "../../concept/LookupSheet";
import { GrammarSheet } from "../grammar/GrammarSheet";
import type { GrammarScope } from "../grammar/grammarModels";
import type { CodePointSpan } from "../TranscriptText";

// What the learner opened from the subtitles: a word or phrase meaning (with save to the notebook), a prepared word,
// or the grammar of a selection or a whole sentence. Only one is open at a time.
export type LookupOverlay =
  | { kind: "concept"; segment: TranscriptSegmentView; learningObjectId: string }
  | { kind: "lookup"; segment: TranscriptSegmentView; span: CodePointSpan }
  | { kind: "grammar"; segment: TranscriptSegmentView; span: CodePointSpan; scope: GrammarScope };

export function useLookupOverlay({ pause, onLookedUp }: {
  pause: () => void;
  // A word or phrase was looked up: the screen reports it to the learning log.
  onLookedUp: (segment: TranscriptSegmentView, span: CodePointSpan) => void;
}) {
  const [overlay, setOverlay] = useState<LookupOverlay | null>(null);

  function onGrammar(segment: TranscriptSegmentView, span: CodePointSpan | null) {
    pause();
    window.getSelection()?.removeAllRanges();
    setOverlay({
      kind: "grammar", segment, span: span ?? { start: 0, end: [...segment.text].length },
      scope: span ? "selection" : "sentence",
    });
  }

  function onLookup(segment: TranscriptSegmentView, span: CodePointSpan) {
    pause();
    window.getSelection()?.removeAllRanges();
    setOverlay({ kind: "lookup", segment, span });
    onLookedUp(segment, span);
  }

  function onOccurrenceTap(segment: TranscriptSegmentView, learningObjectIds: string[]) {
    if (learningObjectIds.length === 0) return;
    const occurrences = segment.learning_objects.filter(item => learningObjectIds.includes(item.learning_object_id));
    const grammar = occurrences.find(item => item.grammar_key);
    const vocabulary = occurrences.filter(item => !item.grammar_key);
    if (grammar && vocabulary.length === 0) {
      setOverlay({ kind: "grammar", segment, span: { start: grammar.start_codepoint, end: grammar.end_codepoint }, scope: "selection" });
      pause();
      window.getSelection()?.removeAllRanges();
      return;
    }
    if (!vocabulary.length) return;
    // A span can carry several senses of one phrase; the concept API takes one learning object, so open the widest.
    const chosen = vocabulary.reduce((best, item) =>
      item.end_codepoint - item.start_codepoint > best.end_codepoint - best.start_codepoint ? item : best);
    pause();
    setOverlay({ kind: "concept", segment, learningObjectId: chosen.learning_object_id });
  }

  return { overlay, close: () => setOverlay(null), onGrammar, onLookup, onOccurrenceTap };
}

export function LookupPanel({ libraryItemId, regionId, supportLanguage, overlay, onClose }: {
  libraryItemId: string;
  regionId: string | undefined;
  supportLanguage: string;
  overlay: LookupOverlay | null;
  onClose: () => void;
}) {
  if (!overlay) return null;
  if (overlay.kind === "concept") {
    return <ConceptSheet libraryItemId={libraryItemId} regionId={regionId} learningObjectId={overlay.learningObjectId} onClose={onClose} />;
  }
  if (overlay.kind === "grammar") {
    return <GrammarSheet
      key={`${overlay.segment.segment_id}:${overlay.span.start}:${overlay.span.end}:${overlay.scope}`}
      libraryItemId={libraryItemId} segmentId={overlay.segment.segment_id} span={overlay.span}
      initialScope={overlay.scope} supportLanguage={supportLanguage} onClose={onClose} />;
  }
  return <LookupSheet libraryItemId={libraryItemId} regionId={regionId} segment={overlay.segment} span={overlay.span} onClose={onClose} />;
}
