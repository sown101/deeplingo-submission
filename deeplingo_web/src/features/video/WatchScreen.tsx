import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { AgentPanelContext } from "../../app/AgentPanelContext";
import { useContainer } from "../../app/container";
import { SegmentedControl } from "../../design/Controls";
import { Icon } from "../../design/Icon";
import { youTubeEmbedSrc } from "../../lib/media";
import type { TranscriptSegmentView } from "../../lib/api/dto";
import { T, useT } from "../../i18n/i18n";
import type { PracticeSuggestion } from "../companion/companionModels";
import { shadowingSegments } from "../speaking/ShadowingPanel";
import { VideoAgentPanel } from "./VideoAgentPanel";
import { SegmentResolver } from "./segmentResolver";
import { useWatchPlayer } from "./useWatchPlayer";
import type { DictationCheck } from "./dictation/DictationPanel";
import { LookupPanel, useLookupOverlay } from "./lookup/LookupPanel";
import { RegionPracticePanel, type PracticeTab } from "./region/RegionPracticePanel";
import { TranscriptPanel } from "./transcript/TranscriptPanel";
import { useBilingualSubtitles } from "./transcript/useBilingualSubtitles";
import { PartsBar, PreparationNote, partKey } from "./workspace/PartsBar";
import { RegionResultCard } from "./workspace/RegionResultCard";
import { useStudyParts, workspaceQueryKey } from "./workspace/useStudyParts";
import { useWatchPosition } from "./workspace/useWatchPosition";
import { formatClock, preparationInProgress, regionFromParam, regionIdOf, regionSegments } from "./workspace/workspaceModels";
import "./watch.css";

const WORKSPACE_RETRY_MS = 30_000;
// M1 S2: while the study part is being prepared on the server, read its status again.
const PREPARATION_POLL_MS = 5_000;
// The workspace panel. Dictation and Shadowing are tools: they drive the shared player and,
// when closed, return it to where the learner was watching.
const TABS = [
  { id: "watch", label: "Transcript", tool: false },
  { id: "dictation", label: "Dictation", tool: true },
  { id: "shadowing", label: "Shadowing", tool: true },
  { id: "questions", label: "Questions", tool: false },
] as const;
type Tab = (typeof TABS)[number]["id"];

function tabOf(value: string | null): Tab {
  return TABS.some((tab) => tab.id === value) ? (value as Tab) : "watch";
}

function isTool(tab: Tab): boolean {
  return TABS.some((item) => item.id === tab && item.tool);
}

function contextStart(raw: string | null): number | null {
  const value = raw === null ? Number.NaN : Number(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

// One workspace per Library item: a new item starts with fresh player and panel state.
export function WatchScreen() {
  const { libraryItemId = "" } = useParams();
  return <VideoWorkspace key={libraryItemId} libraryItemId={libraryItemId} />;
}

function VideoWorkspace({ libraryItemId }: { libraryItemId: string }) {
  const t = useT();
  const { playback } = useContainer();
  const agentPanel = useContext(AgentPanelContext);

  const playableQuery = useQuery({
    queryKey: ["playable", libraryItemId],
    queryFn: () => playback.getPlayableVideo(libraryItemId),
    enabled: libraryItemId.length > 0,
    retry: false,
  });
  const transcriptQuery = useQuery({
    queryKey: ["transcript", libraryItemId],
    queryFn: () => playback.getTranscript(libraryItemId),
    enabled: libraryItemId.length > 0,
    retry: false,
  });
  // Always read fresh: the resume point may have moved on another tab or device. A failed
  // read is retried in the background; until one succeeds nothing is saved.
  const workspaceQuery = useQuery({
    queryKey: workspaceQueryKey(libraryItemId),
    queryFn: () => playback.getWorkspace(libraryItemId),
    enabled: libraryItemId.length > 0,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: (query) =>
      query.state.status === "error"
        ? WORKSPACE_RETRY_MS
        : preparationInProgress(query.state.data?.region?.preparation) ? PREPARATION_POLL_MS : false,
  });
  // 2026-11-05: the study region opens on a part cut by AI, so the learner never has to choose one first.
  const partsQuery = useQuery({
    queryKey: ["video-parts", libraryItemId],
    queryFn: () => playback.getParts(libraryItemId),
    enabled: libraryItemId.length > 0 && transcriptQuery.isSuccess,
    retry: false,
    staleTime: Infinity,
  });

  const video = playableQuery.data;
  const transcript = transcriptQuery.data;
  const workspace = workspaceQuery.data;
  const region = workspace?.region ?? null;
  const regionId = region ? regionIdOf(region) : undefined;
  const translating = useBilingualSubtitles(libraryItemId, transcript);
  const resolver = useMemo(() => (transcript ? new SegmentResolver(transcript.segments) : null), [transcript]);

  const player = useWatchPlayer();
  const { positionMs, pause, seek } = player;
  // The agent paused the video for the learner; it stays paused until they resume it.
  const [agentHold, setAgentHold] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = tabOf(searchParams.get("mode"));
  // M1 S7d: "Xem ngữ cảnh" from Quick review opens the video at that sentence (?at=ms).
  const atMs = contextStart(searchParams.get("at"));
  const [heldMs, setHeldMs] = useState<number | null>(null);
  // M1 S3: the sentence a companion suggestion opened a tool on, until the tool is closed.
  const [practiceFrom, setPracticeFrom] = useState<string | null>(null);
  const [resultOpen, setResultOpen] = useState(false);

  // An agent card opens the video at a part: `?region=<first sentence>_<last sentence>`.
  const requestedRegion = useMemo(() => regionFromParam(searchParams.get("region")), [searchParams]);
  const studyParts = useStudyParts({
    libraryItemId, workspaceQuery, parts: partsQuery.data?.parts, region, seek, play: player.play,
    requested: requestedRegion,
  });
  const { currentPart, nextPart } = studyParts;
  const partNumber = currentPart
    ? (partsQuery.data?.parts ?? []).findIndex((part) => partKey(part) === partKey(currentPart)) + 1 : 0;
  // The result belongs to one part: choosing another closes it.
  useEffect(() => setResultOpen(false), [regionId]);

  const workspaceSettled = workspaceQuery.status !== "pending";
  const save = useCallback(
    (ms: number, keepalive: boolean) => playback.saveWatchPosition(libraryItemId, ms, { keepalive }),
    [playback, libraryItemId],
  );
  // With a tool open the resume point is where the tool returns, not where its clip plays.
  const moveWatched = useCallback(
    (ms: number) => (isTool(tab) ? setHeldMs(ms) : seek(ms)),
    [tab, seek],
  );
  const resume = useWatchPosition({
    status: video === undefined ? "pending" : workspaceQuery.status,
    savedPositionMs: atMs ?? workspace?.position_ms ?? null,
    positionMs,
    playing: player.playing,
    heldPositionMs: heldMs,
    seek: moveWatched,
    save,
  });
  const { resumedAt, clearResumed } = resume;

  // Opened straight into a tool (a deep link): it returns to the resume point.
  useEffect(() => {
    if (isTool(tab) && heldMs === null && workspaceSettled && video !== undefined) {
      setHeldMs(workspace?.position_ms ?? positionMs);
    }
  }, [tab, heldMs, workspaceSettled, video, workspace, positionMs]);

  const activeSegment = resolver?.resolve(positionMs) ?? null;
  const activeSegmentId = useRef<string | null>(null);
  activeSegmentId.current = activeSegment?.segment_id ?? null;
  const onAgentSegmentChange = agentPanel?.onSegmentChange;
  useEffect(() => {
    onAgentSegmentChange?.(activeSegment?.segment_id ?? null);
    return () => onAgentSegmentChange?.(null);
  }, [onAgentSegmentChange, activeSegment?.segment_id]);
  const watching = useMemo(() => ({
    item: libraryItemId,
    segmentId: () => activeSegmentId.current,
    onTalk: () => { pause(); setAgentHold(true); },
  }), [libraryItemId, pause]);

  // Changing tabs never reloads the player. Opening a tool remembers the video position;
  // closing it returns the player there, paused.
  function selectTab(next: Tab) {
    setResultOpen(false);
    if (!isTool(next)) setPracticeFrom(null);
    if (next === tab) return;
    if (isTool(next)) {
      pause();
      if (!isTool(tab)) setHeldMs(positionMs);
    } else if (isTool(tab)) {
      pause();
      if (heldMs !== null) seek(heldMs);
      setHeldMs(null);
    }
    setSearchParams(next === "watch" ? {} : { mode: next }, { replace: true });
  }

  const inRegion = useMemo(
    () => new Set(transcript ? regionSegments(transcript.segments, region).map((segment) => segment.segment_id) : []),
    [transcript, region],
  );
  // On this page the persistent Tata launcher talks about the study part (no separate buttons).
  const onLauncherChange = agentPanel?.onLauncherChange;
  const launcherSegmentId = region
    ? activeSegment && inRegion.has(activeSegment.segment_id) ? activeSegment.segment_id : region.start_segment_id
    : null;
  const launcherTitle = partNumber > 0 ? t("Talk about part {n}", { n: partNumber }) : t("Talk about this part");
  const launcherSubtitle = t("Tata knows what you are practising");
  useEffect(() => {
    onLauncherChange?.(launcherSegmentId
      ? { title: launcherTitle, subtitle: launcherSubtitle, segmentId: launcherSegmentId } : null);
  }, [onLauncherChange, launcherSegmentId, launcherTitle, launcherSubtitle]);
  useEffect(() => () => onLauncherChange?.(null), [onLauncherChange]);
  // Tools practise the study region when one is chosen, otherwise the whole transcript.
  const toolSource = useMemo(() => {
    if (!transcript) return [];
    const scoped = regionSegments(transcript.segments, region);
    return scoped.length > 0 ? scoped : transcript.segments;
  }, [transcript, region]);
  const practiceSegments = useMemo(() => toolSource.filter((segment) => segment.text.trim()), [toolSource]);
  const shadowable = useMemo(() => shadowingSegments(toolSource), [toolSource]);
  const watchedMs = heldMs ?? positionMs;
  // Practice starts at the sentence the companion suggested, else the one being watched (or the
  // region's first sentence).
  const startAt = (list: TranscriptSegmentView[]) => {
    const suggested = practiceFrom ? list.findIndex((segment) => segment.segment_id === practiceFrom) : -1;
    return suggested >= 0 ? suggested : Math.max(0, list.findIndex((segment) => segment.end_ms > watchedMs));
  };
  const toolKey = `${regionId ?? "all"}-${practiceFrom ?? ""}`;

  // The companion only suggests: the tool opens when the learner chooses it.
  function openPractice(suggestion: PracticeSuggestion) {
    setPracticeFrom(suggestion.segment_id);
    selectTab(suggestion.tool);
  }

  // M1 S4: the practice log is best effort. A failed report never interrupts practice.
  function record(send: () => Promise<void>) {
    void Promise.resolve().then(send).catch(() => {});
  }
  const lookup = useLookupOverlay({
    pause,
    onLookedUp: (segment, span) => record(() => playback.recordLookup(libraryItemId,
      { id: crypto.randomUUID(), segment_id: segment.segment_id, span, region_id: regionId })),
  });
  function recordDictation(check: DictationCheck) {
    record(() => playback.recordDictation(libraryItemId, { id: crypto.randomUUID(), ...check, region_id: regionId }));
  }

  // The part result opens in the right panel, in place of the transcript or the tool.
  const showResult = resultOpen && region !== null && regionId !== undefined;

  return (
    <section className="stack watch-screen">
      <div className="page-head">
        <Link className="dl-icon-btn" to="/home" aria-label={t("Back home")} title={t("Back home")}><Icon name="back" /></Link>
        <h1>{video ? video.title : <T>Watch</T>}</h1>
      </div>

      <div className="watch-layout">
        <div className="watch-left stack">
          {playableQuery.isLoading ? <p role="status"><T>Loading video…</T></p> : null}
          {playableQuery.isError ? (
            <div className="card error-card" role="alert">
              <p><T>We could not load this video.</T></p>
              <button type="button" className="dl-btn dl-btn--secondary" onClick={() => playableQuery.refetch()}>
                <T>Retry video</T>
              </button>
            </div>
          ) : null}

          {video ? (
            <div className="player-frame">
              <iframe
                ref={player.iframeRef}
                title={video.title}
                src={youTubeEmbedSrc(video.external_video_id, window.location.origin)}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                onLoad={player.onLoad}
              />
            </div>
          ) : null}

          {resume.offeredAt !== null ? (
            <div className="resume-note row between" role="status">
              <span><T v1={formatClock(resume.offeredAt)}>{"You were at {v1}"}</T></span>
              <span className="row">
                <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={resume.acceptOffer}>
                  <T v1={formatClock(resume.offeredAt)}>{"Continue {v1}"}</T>
                </button>
                <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={resume.declineOffer}>
                  <T>Stay here</T>
                </button>
              </span>
            </div>
          ) : null}

          {resumedAt !== null ? (
            <div className="resume-note row between" role="status">
              <span><T v1={formatClock(resumedAt)}>{"Continuing from {v1}"}</T></span>
              <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => { clearResumed(); seek(0); }}>
                <T>Start over</T>
              </button>
            </div>
          ) : null}

          {transcript ? <>
            <div className="region-bar" aria-label={t("Study part")}>
              {region ? (
                <PartsBar
                  parts={partsQuery.data?.parts ?? []}
                  current={currentPart}
                  region={region}
                  busy={studyParts.saving}
                  onChange={(key) => void studyParts.changePart(key)}
                  onFinish={() => { pause(); setResultOpen(true); }}
                  note={<PreparationNote preparation={region.preparation} busy={studyParts.saving} onRetry={() => void studyParts.retryPreparation()} />}
                />
              ) : partsQuery.isFetching || studyParts.saving ? (
                <span role="status"><T>Splitting the video into parts…</T></span>
              ) : partsQuery.isError ? (
                <>
                  <span role="status"><T>We could not split this video into parts.</T></span>
                  <button type="button" className="dl-btn dl-btn--secondary dl-btn--sm" onClick={() => void partsQuery.refetch()}>
                    <T>Try again</T>
                  </button>
                </>
              ) : null}
            </div>
            {studyParts.error ? <p className="region-error" role="alert">{studyParts.error}</p> : null}
          </> : null}

          {agentHold && !player.playing ? <button type="button" className="dl-btn dl-btn--secondary" onClick={() => { player.play(); setAgentHold(false); }}><T>Resume video</T></button> : null}
        </div>
        <div className="watch-right stack">
          <SegmentedControl label={t("Workspace tools")} value={tab} onChange={selectTab} idPrefix="mode"
            panelId={value => value === "watch" ? "transcript-panel" : "mode-panel"}
            items={TABS.map(item => ({ value: item.id, label: t(item.label),
              icon: <Icon name={item.id === "watch" ? "subtitles" : item.id === "dictation" ? "dictation" : item.id === "shadowing" ? "mic" : "questions"} /> }))} />
          {showResult ? (
            <div className="mode-panel region-result-panel">
              <RegionResultCard libraryItemId={libraryItemId} regionId={regionId} region={region} nextPart={nextPart}
                busy={studyParts.saving} onClose={() => setResultOpen(false)}
                onStudyNext={(part) => void studyParts.studyNext(part)} />
            </div>
          ) : tab !== "watch" ? (
            <RegionPracticePanel tab={tab as PracticeTab} libraryItemId={libraryItemId} regionId={regionId} region={region}
              transcript={transcript} practiceSegments={practiceSegments} shadowable={shadowable} toolSource={toolSource}
              toolKey={toolKey} startAt={startAt} player={player} onDictationChecked={recordDictation}
              onShowResult={() => { pause(); setResultOpen(true); }} />
          ) : null}
          <TranscriptPanel
            transcript={transcript} loading={transcriptQuery.isLoading} failed={transcriptQuery.isError}
            onRetry={() => void transcriptQuery.refetch()} activeSegmentId={activeSegment?.segment_id ?? null}
            inRegion={inRegion} visible={tab === "watch" && !showResult} translating={translating} onSeek={seek}
            onOccurrenceTap={lookup.onOccurrenceTap} onLookup={lookup.onLookup} onGrammar={lookup.onGrammar} />
        </div>
      </div>
      {agentPanel?.host ? createPortal(<VideoAgentPanel
        key={region && partKey(region) !== studyParts.autoPartKey.current
          ? `${libraryItemId}:${partKey(region)}` : `${libraryItemId}:no-part`}
        watching={watching} onPractice={openPractice} onPhaseChange={agentPanel.onPhaseChange}
      />, agentPanel.host) : null}

      <LookupPanel libraryItemId={libraryItemId} regionId={regionId} overlay={lookup.overlay} onClose={lookup.close}
        supportLanguage={transcript?.translation_language_code ?? "vi"} />
    </section>
  );
}
