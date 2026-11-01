"""Numerical and MusicXML regressions using measured, independently checked audio."""

import json
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest
from music21 import chord, meter, note, stream, converter, tempo, key, instrument
from scipy.signal import periodogram

from quartetiq.analysis import AnalysisConfig, analyze_notes, write_json
from quartetiq.pitch import PitchConfig, PitchTrack, estimate_pitch, hz_to_cents, midi_to_hz
from quartetiq.score import NoteEvent, generate_score, parse_score
from quartetiq.synthesis import SynthesisConfig, synthesize


@pytest.fixture
def event():
    return NoteEvent("p1-m001-n001", 1, 1, "A4", 69, 0, 2)


@pytest.fixture
def score_path(tmp_path):
    return generate_score(tmp_path / "ode.musicxml")


@pytest.mark.parametrize("midi,hz", [(69, 440), (81, 880), (57, 220), (62, 293.6647679)])
def test_frequency_conversion(midi, hz):
    assert midi_to_hz(midi) == pytest.approx(hz)
    assert float(hz_to_cents(hz * 2 ** (23 / 1200), hz)) == pytest.approx(23)


def test_invalid_frequency():
    assert np.isnan(hz_to_cents(np.array([0, -1, np.nan, np.inf]))).all()
    with pytest.raises(ValueError):
        hz_to_cents(440, 0)
    with pytest.raises(ValueError):
        midi_to_hz(np.nan)


def test_score_roundtrip(score_path):
    events = parse_score(score_path)
    assert events == parse_score(score_path)
    assert len(events) == len({e.id for e in events}) == 30
    assert {e.measure for e in events} == set(range(1, 9))
    assert sum(e.duration_quarters for e in events) == 32
    assert [e.pitch for e in events[:4]] == ["F#4", "F#4", "G4", "A4"]
    assert events[13].beat == 2.5
    assert events[-1].onset_quarters == 30
    assert events[-1].pitch == "D4"
    score = converter.parse(score_path)
    assert score.recurse().getElementsByClass(meter.TimeSignature)[0].ratioString == "4/4"
    assert score.recurse().getElementsByClass(tempo.MetronomeMark)[0].number == 88
    assert score.recurse().getElementsByClass(key.KeySignature)[0].sharps == 2
    assert score.recurse().getElementsByClass(instrument.Violin)
    for bar in score.parts[0].getElementsByClass(stream.Measure):
        assert bar.duration.quarterLength == 4


def test_parser_rest_and_chord(tmp_path):
    part = stream.Part()
    bar = stream.Measure(number=1)
    bar.append(meter.TimeSignature("4/4"))
    bar.append(note.Rest(quarterLength=1))
    bar.append(note.Note("D4", quarterLength=3))
    part.append(bar)
    path = tmp_path / "rest.musicxml"
    part.write("musicxml", fp=path)
    assert parse_score(path)[0].onset_quarters == 1
    bar.replace(bar.notes[0], chord.Chord(["D4", "F#4"], quarterLength=3))
    part.write("musicxml", fp=path)
    with pytest.raises(ValueError, match="Chords"):
        parse_score(path)


@pytest.mark.parametrize("hz", [293.6647679, 440, 660])
def test_pyin_known_tone(hz):
    config = PitchConfig()
    t = np.arange(config.sample_rate) / config.sample_rate
    track = estimate_pitch(.5 * np.sin(2 * np.pi * hz * t), config)
    valid = (track.times > .2) & (track.times < .8) & track.voiced
    assert valid.sum() > 30
    assert abs(float(np.nanmedian(hz_to_cents(track.frequencies[valid], hz)))) < 8


def test_silence_empty_and_invalid(event):
    track = estimate_pitch(np.zeros(22050))
    result = analyze_notes([event], track)[0]
    assert result["status"] == "insufficient_frames"
    assert result["cents_deviation"] is None
    assert len(estimate_pitch(np.array([])).times) == 0
    for samples in (np.array([np.nan]), np.array([np.inf]), np.zeros((2, 2))):
        with pytest.raises(ValueError):
            estimate_pitch(samples)


@pytest.mark.parametrize("cents,bpm", [(-30, 72), (0, 88), (25, 112)])
def test_synthetic_note_accuracy(event, cents, bpm):
    config = SynthesisConfig(cents=cents, bpm=bpm, seed=9)
    audio, truth = synthesize([event], config)
    audio_again, _ = synthesize([event], config)
    np.testing.assert_array_equal(audio, audio_again)
    # Independent FFT check of synthesized pitch, without trusting the sidecar.
    segment = audio[round(.4 * config.sample_rate):round((truth[0]["end_seconds"] - .15) * config.sample_rate)]
    frequencies, power = periodogram(segment, fs=config.sample_rate, nfft=262144)
    measured = frequencies[np.argmax(power)]
    assert abs(float(hz_to_cents(measured, 440)) - cents) < 1
    track = estimate_pitch(audio)
    result = analyze_notes([event], track, config=AnalysisConfig(bpm=bpm))[0]
    assert result["status"] == "ok"
    assert abs(result["cents_deviation"] - cents) < 8


def test_per_note_override_and_tempo(event):
    config = SynthesisConfig(bpm=120)
    _, truth = synthesize([event], config, {event.id: 40})
    assert truth[0]["end_seconds"] - truth[0]["start_seconds"] == 1
    assert truth[0]["frequency_hz"] == pytest.approx(440 * 2 ** (40 / 1200))
    with pytest.raises(ValueError, match="unknown"):
        synthesize([event], config, {"missing": 10})


def test_robust_center_and_unavailable_frames(event):
    times = np.linspace(.3, 1.5, 30)
    hz = np.full(30, 440 * 2 ** (.2 / 12))
    hz[:3] = 880  # boundary frames are excluded
    hz[12] = 1000  # isolated interior outlier must not skew the median
    hz[13:16] = [np.nan, np.inf, 0]
    track = PitchTrack(times, hz, np.ones(30, dtype=bool), np.ones(30))
    result = analyze_notes([event], track)[0]
    assert result["cents_deviation"] == pytest.approx(20)
    assert result["mad_cents"] == pytest.approx(0)
    track = replace(track, probabilities=np.zeros(30))
    assert analyze_notes([event], track)[0]["pitch_center_hz"] is None
    short = replace(event, duration_quarters=.01)
    assert analyze_notes([short], track)[0]["status"] == "insufficient_frames"


def test_strict_json(tmp_path):
    path = write_json(tmp_path / "result.json", {"values": np.array([np.nan, np.inf, 1])})
    assert json.loads(path.read_text()) == {"values": [None, None, 1]}


@pytest.mark.parametrize("factory,kwargs", [
    (PitchConfig, {"fmin": 0}), (PitchConfig, {"fmax": np.nan}),
    (PitchConfig, {"resolution": 0}), (PitchConfig, {"hop_length": 0}),
    (AnalysisConfig, {"bpm": 0}), (AnalysisConfig, {"interior_fraction": .5}),
    (AnalysisConfig, {"start_seconds": np.inf}), (SynthesisConfig, {"cents": np.nan}),
])
def test_invalid_configs(factory, kwargs):
    with pytest.raises(ValueError):
        factory(**kwargs)


def test_cli_demo(tmp_path):
    subprocess.run([sys.executable, "-m", "quartetiq", "demo", "--output-dir", str(tmp_path), "--cents", "20"], check=True, capture_output=True, text=True)
    results = json.loads((tmp_path / "analysis.json").read_text())
    assert len(results["notes"]) == 30
    assert all(row["status"] == "ok" for row in results["notes"])
    assert max(abs(row["cents_deviation"] - 20) for row in results["notes"]) < 10
    assert (tmp_path / "synthetic.truth.json").exists()
    assert any(value is None for value in results["frames"]["frequency_hz"])
