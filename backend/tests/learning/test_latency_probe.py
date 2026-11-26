"""The latency probe's arithmetic (scripts/agent/latency_probe.py); the network part runs only by hand."""
import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "agent" / "latency_probe.py"
_spec = importlib.util.spec_from_file_location("latency_probe", _PATH)
probe = importlib.util.module_from_spec(_spec)
sys.modules["latency_probe"] = probe  # dataclasses look their module up here
_spec.loader.exec_module(probe)


def test_percentile_is_nearest_rank():
    assert probe.percentile([5, 1, 3, 2, 4], 0.9) == 5
    assert probe.percentile([10], 0.5) == 10
    assert probe.percentile([1, 2, 3, 4], 0.5) == 2


def test_summary_compares_the_median_with_its_target():
    samples = probe.Samples()
    for value in (1000, 1500, 2500):
        samples.add("utterance_end_to_speech_ms", value)
    samples.add("interrupt_to_stop_ms", 450)
    samples.add("interrupt_to_stop_ms", None)  # a timed-out run is not a sample
    rows = {row["metric"]: row for row in probe.summarize(samples)}
    assert rows["utterance_end_to_speech_ms"]["p50"] == 1500
    assert rows["utterance_end_to_speech_ms"]["meets"] is True
    assert rows["interrupt_to_stop_ms"]["n"] == 1 and rows["interrupt_to_stop_ms"]["meets"] is False


def test_frames_are_twenty_milliseconds_and_the_last_is_padded():
    frames = probe.pcm_frames(b"\1" * 1000)
    assert [len(frame) for frame in frames] == [640, 640]
    assert frames[1].endswith(b"\0")
