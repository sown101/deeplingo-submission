import { useEffect, useRef, useState } from "react";
import { Icon } from "../../../design/Icon";
import type { TranscriptSegmentView, VideoTranscriptView } from "../../../lib/api/dto";
import { prefersReducedMotion, resolveScrollBehavior } from "../../../lib/motion";
import { T, useT } from "../../../i18n/i18n";
import { TranscriptText, selectionSpan, type CodePointSpan } from "../TranscriptText";

// The subtitles beside the player: the original line, the meaning under it, the line being played highlighted.
// Selecting text looks it up; the analyse button explains the grammar of the selection or the whole sentence.
export function TranscriptPanel({ transcript, loading, failed, onRetry, activeSegmentId, inRegion, visible,
  translating, onSeek, onOccurrenceTap, onLookup, onGrammar }: {
  transcript: VideoTranscriptView | undefined;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  activeSegmentId: string | null;
  inRegion: Set<string>;
  visible: boolean;
  translating: boolean;
  onSeek: (ms: number) => void;
  onOccurrenceTap: (segment: TranscriptSegmentView, learningObjectIds: string[]) => void;
  onLookup: (segment: TranscriptSegmentView, span: CodePointSpan) => void;
  onGrammar: (segment: TranscriptSegmentView, span: CodePointSpan | null) => void;
}) {
  const t = useT();
  const [showTranslation, setShowTranslation] = useState(true);
  const [showRomanization, setShowRomanization] = useState(false);
  const [following, setFollowing] = useState(true);
  const [manualScroll, setManualScroll] = useState(false);
  const segmentRefs = useRef(new Map<string, HTMLDivElement>());
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const unspaced = transcript ? ["zh", "ja", "th"].includes(transcript.language_code) : false;

  // Auto-follow scroll when the active segment changes and follow is enabled.
  // Reduced-motion preference receives instant, non-animated scrolling.
  useEffect(() => {
    if (!activeSegmentId || !following || manualScroll) return;
    const node = segmentRefs.current.get(activeSegmentId);
    const container = scrollRef.current;
    if (node && container) {
      container.scrollTo({
        top: Math.max(node.offsetTop - container.clientHeight / 3, 0),
        behavior: resolveScrollBehavior(prefersReducedMotion()),
      });
    }
  }, [activeSegmentId, following, manualScroll, visible]);

  const suspend = () => { setManualScroll(true); setFollowing(false); };
  return (
    <div id="transcript-panel" role="tabpanel" aria-labelledby="mode-watch" className="watch-transcript stack" hidden={!visible}>
      {loading ? <p role="status"><T>Loading transcript…</T></p> : null}
      {failed ? (
        <div className="card error-card" role="alert">
          <p><T>The transcript could not be loaded.</T></p>
          <button type="button" className="dl-btn dl-btn--secondary" onClick={onRetry}><T>Retry transcript</T></button>
        </div>
      ) : null}
      {transcript ? (
        <>
          <div className="transcript-scroll" ref={scrollRef} role="region" aria-label={t("Transcript")}
            onWheel={suspend} onTouchMove={suspend}>
            {transcript.segments.map((segment) => (
              <TranscriptRow
                key={segment.segment_id}
                segment={segment}
                active={activeSegmentId === segment.segment_id}
                inRegion={inRegion.has(segment.segment_id)}
                showTranslation={showTranslation}
                showRomanization={showRomanization}
                registerRef={(node) => {
                  if (node) segmentRefs.current.set(segment.segment_id, node);
                  else segmentRefs.current.delete(segment.segment_id);
                }}
                unspaced={unspaced}
                onTap={() => onSeek(segment.start_ms)}
                onOccurrenceTap={(ids) => onOccurrenceTap(segment, ids)}
                onLookup={(span) => onLookup(segment, span)}
                onGrammar={(span) => onGrammar(segment, span)}
              />
            ))}
          </div>
          <div className="row between">
            <span className="row">
              {transcript.segments.some((s) => s.translation) ? (
                <label className="toggle">
                  <input type="checkbox" checked={showTranslation} onChange={(e) => setShowTranslation(e.target.checked)} />
                  <T>Translation</T>
                </label>
              ) : translating ? <span className="muted small" role="status"><T>Translating the subtitles…</T></span> : null}
              {transcript.segments.some((s) => s.romanizations.length > 0) ? (
                <label className="toggle">
                  <input type="checkbox" checked={showRomanization} onChange={(e) => setShowRomanization(e.target.checked)} />
                  <T>Romanization</T>
                </label>
              ) : null}
            </span>
            {!following ? (
              <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => { setManualScroll(false); setFollowing(true); }}>
                <T>Follow playback</T>
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

function TranscriptRow({ segment, active, inRegion, showTranslation, showRomanization, registerRef, unspaced,
  onTap, onOccurrenceTap, onLookup, onGrammar }: {
  segment: TranscriptSegmentView;
  active: boolean;
  inRegion: boolean;
  showTranslation: boolean;
  showRomanization: boolean;
  registerRef: (node: HTMLDivElement | null) => void;
  unspaced: boolean;
  onTap: () => void;
  onOccurrenceTap: (learningObjectIds: string[]) => void;
  onLookup: (span: CodePointSpan) => void;
  onGrammar: (span: CodePointSpan | null) => void;
}) {
  const t = useT();
  const textRef = useRef<HTMLDivElement | null>(null);
  // A text selection inside this sentence is looked up instead of seeking the video.
  function lookupSelection(): boolean {
    const span = textRef.current ? selectionSpan(textRef.current) : null;
    if (span) onLookup(span);
    return span !== null;
  }
  const romanization = showRomanization && segment.romanizations.length > 0 ? segment.romanizations[0].text : null;
  const translation = showTranslation && segment.translation ? segment.translation.text : null;
  const className = ["transcript-row", active ? "active" : "", inRegion ? "in-region" : ""].filter(Boolean).join(" ");
  return (
    <div ref={registerRef} className={className} data-in-region={inRegion ? "true" : undefined} role="group"
      onClick={() => { if (!lookupSelection()) onTap(); }}>
      <button type="button" className="dl-icon-btn sentence-analysis" aria-label={t("Analyse sentence")} title={t("Analyse sentence")}
        onMouseDown={event => event.preventDefault()}
        onClick={event => { event.stopPropagation(); onGrammar(textRef.current ? selectionSpan(textRef.current) : null); }}><Icon name="analyze" /></button>
      <div ref={textRef} role="button" tabIndex={0} aria-label={segment.text}
        onKeyDown={event => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onTap(); } }}>
        <TranscriptText text={segment.text} occurrences={segment.learning_objects} unspaced={unspaced}
          onOccurrenceTap={onOccurrenceTap} onWordTap={onLookup} />
      </div>
      {romanization ? <p className="romanization">{romanization}</p> : null}
      {translation && segment.translation ? <p className="translation" lang={segment.translation.language_code}>{translation}</p> : null}
    </div>
  );
}
