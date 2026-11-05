"""Bundled data integrity, upload processing, and Streamlit smoke tests."""
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from streamlit.testing.v1 import AppTest

from quartetiq.comparison import compare_takes
from quartetiq.dashboard import analyze_upload, dataset_key, load_demo
from quartetiq.score import parse_score

ROOT = Path(__file__).resolve().parents[1]


def test_measured_demo_dataset():
    manifest, results = load_demo(ROOT / "demo")
    score = ROOT / "demo" / manifest["score"]
    assert hashlib.sha256(score.read_bytes()).hexdigest() == manifest["score_sha256"]
    events = parse_score(score)
    for entry, result in zip(manifest["takes"], results):
        for kind in ("audio", "analysis"):
            assert hashlib.sha256((ROOT / "demo" / entry[kind]).read_bytes()).hexdigest() == entry[f"{kind}_sha256"]
        assert result["alignment"] == "automatic duration-constrained DTW"
        assert len(result["notes"]) == 30
        assert all(n["status"] == "ok" for n in result["notes"])
        truth = json.loads((ROOT / "demo" / entry["truth"]).read_text())["notes"]
        assert max(abs(n["cents_deviation"] - t["cents"]) for n, t in zip(result["notes"], truth)) < 8
        # Recompute actual medians from stored pYIN frames, not from truth inputs.
        from quartetiq.analysis import AnalysisConfig, analyze_notes
        from quartetiq.alignment import NoteAlignment
        from quartetiq.pitch import PitchConfig, PitchTrack
        frames = result["frames"]
        track = PitchTrack(np.array(frames["time_seconds"]), np.array(frames["frequency_hz"], dtype=float),
                           np.array(frames["voiced"]), np.array(frames["voiced_probability"]))
        measured = analyze_notes(events, track, PitchConfig(**result["pitch_config"]),
                                 AnalysisConfig(**result["analysis_config"]),
                                 alignment=[NoteAlignment(**a) for a in result["note_alignment"]])
        assert [n["cents_deviation"] for n in measured] == [n["cents_deviation"] for n in result["notes"]]
    comparison = compare_takes(results)
    # The improving note's middle take measures 15.02 cents: the strict
    # measured >15 rule must retain it, despite its 12-cent synthesis target.
    assert [n["note_id"] for n in comparison["persistent_errors"]] == [events[2].id, events[6].id]
    assert comparison["notes"][6]["takes"][-1]["absolute_cents_error"] < 15
    assert comparison["notes"][6]["first_to_last_improvement_cents"] > 30
    assert all(abs(n["cents_deviation"]) < 10 for r in results for n in r["notes"] if n["measure"] >= 5)
    assert comparison["improvement"]["percentage_reduction"] > 50


def test_demo_app_and_upload_empty_state():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert len(app.metric) == 4
    assert any("Recurring problem" in m.label for m in app.metric)
    assert len(app.dataframe) >= 2
    app.radio[0].set_value("Upload my recordings").run()
    assert not app.exception
    assert app.button[0].disabled
    assert len(app.metric) == 0  # No stale demo results displayed as uploaded results.


def test_upload_validation_and_dataset_key():
    with pytest.raises(ValueError, match="MusicXML"):
        analyze_upload(b"", b"bad")
    with pytest.raises(ValueError, match="WAV"):
        analyze_upload(b"score", b"bad")
    assert dataset_key(b"a", [b"b", b"c"]) != dataset_key(b"a", [b"c", b"b"])
    assert dataset_key(b"a", [b"bc"]) != dataset_key(b"ab", [b"c"])


def test_uploaded_silence_produces_no_fake_measurements():
    manifest, _ = load_demo(ROOT / "demo")
    score = (ROOT / "demo" / manifest["score"]).read_bytes()
    recording = io.BytesIO()
    sf.write(recording, np.zeros(22050), 22050, format="WAV")
    result = analyze_upload(score, recording.getvalue())
    assert result["score"] == "uploaded_score.musicxml"
    assert all(n["cents_deviation"] is None for n in result["notes"])
    assert all(n["alignment_status"] == "failed" for n in result["notes"])


def test_uploaded_recording_matches_bundled_analysis():
    manifest, bundled = load_demo(ROOT / "demo")
    result = analyze_upload((ROOT / "demo" / manifest["score"]).read_bytes(),
                            (ROOT / "demo" / manifest["takes"][0]["audio"]).read_bytes())
    assert result["notes"] == bundled[0]["notes"]
    assert result["note_alignment"] == bundled[0]["note_alignment"]


def test_upload_button_caching_and_stale_results(monkeypatch):
    from streamlit.delta_generator import DeltaGenerator
    import streamlit as st
    import quartetiq.dashboard as dashboard
    st.cache_data.clear()
    manifest, results = load_demo(ROOT / "demo")
    files = {"MusicXML score": b"xml", "Take 1 (earliest)": b"wav1", "Take 2": b"wav2", "Take 3 (latest)": b"wav3"}
    calls = []

    def upload_widget(self, label, **kwargs):
        return io.BytesIO(files[label])

    def analyze(score, wav):
        calls.append((score, wav))
        return results[int(wav[-1:]) - 1]

    monkeypatch.setattr(DeltaGenerator, "file_uploader", upload_widget)
    monkeypatch.setattr(st, "file_uploader", lambda label, **kwargs: upload_widget(None, label, **kwargs))
    monkeypatch.setattr(dashboard, "analyze_upload", analyze)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.radio[0].set_value("Upload my recordings").run()
    assert calls == []
    app.button[0].click().run()
    assert not app.exception
    assert len(calls) == 3
    assert len(app.metric) == 4
    app.button[0].click().run()
    assert len(calls) == 3  # Cache survives reruns and explicit re-analysis.
    files["MusicXML score"] = b"new score"
    app.run()
    assert not app.exception
    assert len(app.metric) == 0
    st.cache_data.clear()


def test_app_warns_about_unreliable_results(monkeypatch):
    from copy import deepcopy
    import streamlit as st
    import quartetiq.dashboard as dashboard
    st.cache_data.clear()
    manifest, results = load_demo(ROOT / "demo")
    results = deepcopy(results)
    results[0]["notes"][0].update(status="alignment_uncertain", alignment_status="uncertain", cents_deviation=None)
    monkeypatch.setattr(dashboard, "load_demo", lambda _: (manifest, results))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert any("excluded, not treated as in tune" in warning.value for warning in app.warning)
    st.cache_data.clear()
