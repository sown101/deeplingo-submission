import type { TranscriptSegmentView, VideoTranscriptView } from "../../../lib/api/dto";
import { T } from "../../../i18n/i18n";
import { DictationPanel, type DictationCheck } from "../dictation/DictationPanel";
import { QuestionsPanel } from "../questions/QuestionsPanel";
import { ShadowingPanel } from "../../speaking/ShadowingPanel";
import type { useWatchPlayer } from "../useWatchPlayer";
import { formatClock, type StudyRegionView } from "../workspace/workspaceModels";

export type PracticeTab = "dictation" | "shadowing" | "questions";

// "Luyện vùng": Dictation, Shadowing and Questions on the sentences of the study part. Every attempt is stored
// by the server under this part, so the part's result card can add them up. Talking about the part goes
// through the page's Tata launcher.
export function RegionPracticePanel({ tab, libraryItemId, regionId, region, transcript, practiceSegments, shadowable,
  toolSource, toolKey, startAt, player, onDictationChecked, onShowResult }: {
  tab: PracticeTab;
  libraryItemId: string;
  regionId: string | undefined;
  region: StudyRegionView | null;
  transcript: VideoTranscriptView | undefined;
  practiceSegments: TranscriptSegmentView[];
  shadowable: TranscriptSegmentView[];
  toolSource: TranscriptSegmentView[];
  toolKey: string;
  startAt: (list: TranscriptSegmentView[]) => number;
  player: ReturnType<typeof useWatchPlayer>;
  onDictationChecked: (check: DictationCheck) => void;
  onShowResult: () => void;
}) {
  return (
    <div id="mode-panel" role="tabpanel" aria-labelledby={`mode-${tab}`} className="mode-panel">
      {region ? (
        <div className="region-practice__head">
          <span className="muted small">
            <T v1={formatClock(region.start_ms)} v2={formatClock(region.end_ms)}>{"Practising {v1}–{v2}"}</T>
          </span>
          <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={onShowResult}><T>Part result</T></button>
        </div>
      ) : null}
      {!transcript ? <p role="status"><T>Loading transcript…</T></p>
        : tab === "dictation" ? (
          <DictationPanel key={`dictation-${toolKey}`} segments={practiceSegments} languageCode={transcript.language_code}
            unspaced={["zh", "ja", "th"].includes(transcript.language_code)} startIndex={startAt(practiceSegments)}
            player={player} onChecked={onDictationChecked} />
        ) : tab === "shadowing" ? (
          <ShadowingPanel key={`shadowing-${toolKey}`} libraryItemId={libraryItemId} regionId={regionId} segments={shadowable}
            languageCode={transcript.language_code} startIndex={startAt(shadowable)} player={player} />
        ) : (
          <QuestionsPanel libraryItemId={libraryItemId}
            regionKey={`${toolKey}-${region?.preparation?.status ?? ""}-${region?.preparation?.questions_status ?? ""}`}
            segments={toolSource} languageCode={transcript.language_code}
            onPlaySentence={(segment) => player.playClip(segment.start_ms, segment.end_ms)} />
        )}
    </div>
  );
}
