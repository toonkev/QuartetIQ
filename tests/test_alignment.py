"""Alignment checks against unchanged synthesizer truth and independent tracks."""
import json
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest
import soundfile as sf

from quartetiq.alignment import align_notes
from quartetiq.analysis import AnalysisConfig, analyze_notes
from quartetiq.pitch import PitchTrack, estimate_pitch
from quartetiq.score import generate_score, parse_score
from quartetiq.synthesis import SynthesisConfig, synthesize


@pytest.fixture(scope="module")
def events(tmp_path_factory):
    return parse_score(generate_score(tmp_path_factory.mktemp("score") / "ode.musicxml"))


@pytest.mark.parametrize("bpm,start,cents", [(88, .25, 0), (88, 2.3, 25), (96.8, .7, -30), (79.2, .4, 35)])
def test_full_take(events, bpm, start, cents):
    audio, truth = synthesize(events, SynthesisConfig(bpm=bpm, start_seconds=start, cents=cents))
    track = estimate_pitch(audio)
    alignment = align_notes(events, track, audio)
    assert all(a.alignment_status == "aligned" for a in alignment), alignment
    errors = np.array([[a.start_seconds - t["start_seconds"], a.end_seconds - t["end_seconds"]]
                       for a, t in zip(alignment, truth)])
    print(f"\nbpm={bpm} start={start}: boundary MAE={np.mean(np.abs(errors)):.6f}s max={np.max(np.abs(errors)):.6f}s")
    assert np.max(np.abs(errors)) < .06
    # Deliberately wrong manual timing must have no effect on automatic analysis.
    results = analyze_notes(events, track, config=AnalysisConfig(bpm=150, start_seconds=5), alignment=alignment)
    assert all(r["status"] == "ok" for r in results)
    assert max(abs(r["cents_deviation"] - cents) for r in results) < 10
    assert alignment[0].end_seconds == alignment[1].start_seconds
    assert alignment[0].note_id != alignment[1].note_id


def test_local_tempo_variation(events):
    # Independently assemble notes with varying durations; do not alter truth.
    audio = np.zeros(round(1.1 * 22050))
    truth = []
    for i, e in enumerate(events[:12]):
        segment, rows = synthesize([replace(e, onset_quarters=0)],
                                  SynthesisConfig(bpm=88 * (1 + .1 * np.sin(i)), start_seconds=0))
        duration = round(rows[0]["end_seconds"] * 22050)
        offset = len(audio) / 22050
        truth.append((offset, offset + duration / 22050))
        audio = np.r_[audio, segment[:duration]]
    audio = np.r_[audio, np.zeros(5512)]
    track = estimate_pitch(audio)
    alignment = align_notes(events[:12], track, audio)
    assert all(a.alignment_status == "aligned" for a in alignment), alignment
    errors = [abs(value - target) for a, pair in zip(alignment, truth)
              for value, target in zip((a.start_seconds, a.end_seconds), pair)]
    print(f"\nlocal tempo: boundary MAE={np.mean(errors):.6f}s max={max(errors):.6f}s")
    assert max(errors) < .06


def test_repeated_without_onset_evidence(events):
    times = np.arange(0, 1.4, .01)
    track = PitchTrack(times, np.full(len(times), 440 * 2 ** ((66 - 69) / 12)),
                       np.ones(len(times), dtype=bool), np.ones(len(times)))
    alignment = align_notes(events[:2], track)
    assert [a.alignment_status for a in alignment] == ["uncertain", "uncertain"]
    assert all(r["cents_deviation"] is None for r in analyze_notes(events[:2], track, alignment=alignment))


@pytest.mark.parametrize("kind", ["empty", "silence", "wrong", "short", "low_probability"])
def test_failed_correspondence(events, kind):
    times = np.arange(0, 22, .01)
    track = PitchTrack(times, np.full(len(times), 1000.), np.ones(len(times), dtype=bool), np.ones(len(times)))
    if kind == "empty":
        track = PitchTrack(np.array([]), np.array([]), np.array([], dtype=bool), np.array([]))
    if kind == "silence":
        track = replace(track, voiced=np.zeros(len(times), dtype=bool))
    if kind == "low_probability":
        track = replace(track, probabilities=np.zeros(len(times)))
    if kind == "short":
        track = PitchTrack(times[:10], track.frequencies[:10], track.voiced[:10], track.probabilities[:10])
    alignment = align_notes(events, track)
    assert len(alignment) == len(events)
    assert all(a.alignment_status == "failed" for a in alignment)
    assert all(r["cents_deviation"] is None for r in analyze_notes(events, track, alignment=alignment))


def test_rest_and_pitch_only(events):
    selected = [replace(events[0], duration_quarters=1),
                replace(events[2], onset_quarters=2)]
    times = np.arange(0, 2.5, .01)
    hz = np.full(len(times), np.nan)
    hz[(times >= .4) & (times < 1)] = 440 * 2 ** ((66 - 69) / 12)
    hz[(times >= 1.6) & (times < 2.2)] = 440 * 2 ** ((67 - 69) / 12)
    track = PitchTrack(times, hz, np.isfinite(hz), np.isfinite(hz).astype(float))
    alignment = align_notes(selected, track)
    assert all(a.alignment_status == "aligned" for a in alignment), alignment
    assert alignment[1].start_seconds == pytest.approx(1.6, abs=.03)
    assert alignment[0].end_seconds == pytest.approx(1, abs=.03)


def test_validation(events):
    track = PitchTrack(np.arange(10.) / 100, np.ones(10), np.ones(10, dtype=bool), np.ones(10))
    with pytest.raises(ValueError, match="ordered"):
        align_notes(events[::-1], track)
    with pytest.raises(ValueError, match="uniformly"):
        align_notes(events, replace(track, times=np.zeros(10)))
    with pytest.raises(ValueError, match="matching"):
        align_notes(events, replace(track, frequencies=np.ones(9)))
    with pytest.raises(ValueError, match="exactly"):
        analyze_notes(events, track, alignment=[])
    alignment = align_notes(events, track)
    with pytest.raises(ValueError, match="boundaries"):
        analyze_notes(events, track, alignment=[replace(alignment[0], alignment_status="aligned"), *alignment[1:]])


def test_cli_auto(tmp_path):
    score = generate_score(tmp_path / "score.musicxml")
    events = parse_score(score)
    audio, _ = synthesize(events, SynthesisConfig(bpm=96.8, start_seconds=1.5, cents=20))
    wav = tmp_path / "take.wav"
    sf.write(wav, audio, 22050, subtype="FLOAT")
    output = tmp_path / "result.json"
    subprocess.run([sys.executable, "-m", "quartetiq", "analyze", str(score), str(wav),
                    "--auto-align", "--output", str(output)], check=True, capture_output=True)
    result = json.loads(output.read_text())
    assert result["schema_version"] == 2
    assert len(result["note_alignment"]) == 30
    assert all(r["status"] == "ok" for r in result["notes"])
    assert max(abs(r["cents_deviation"] - 20) for r in result["notes"]) < 10
