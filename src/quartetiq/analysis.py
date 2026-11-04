"""Score-relative pitch centers using automatic or constant-tempo boundaries."""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from quartetiq.alignment import NoteAlignment
from quartetiq.pitch import PitchConfig, PitchTrack, hz_to_cents, midi_to_hz
from quartetiq.score import NoteEvent


@dataclass(frozen=True)
class AnalysisConfig:
    """Known performance timing and requirements for a robust median center."""

    bpm: float = 88.0
    start_seconds: float = .25
    interior_fraction: float = .15
    min_voiced_probability: float = .8
    min_frames: int = 5

    def __post_init__(self) -> None:
        if not all(np.isfinite(v) for v in (self.bpm, self.start_seconds, self.interior_fraction, self.min_voiced_probability)):
            raise ValueError("Analysis parameters must be finite")
        if self.bpm <= 0 or self.start_seconds < 0 or not 0 <= self.interior_fraction < .5:
            raise ValueError("Invalid timing or interior fraction")
        if not 0 <= self.min_voiced_probability <= 1 or self.min_frames < 1:
            raise ValueError("Invalid confidence or minimum frame count")


def analyze_notes(events: Sequence[NoteEvent], track: PitchTrack,
                  pitch_config: PitchConfig = PitchConfig(),
                  config: AnalysisConfig = AnalysisConfig(),
                  alignment: Sequence[NoteAlignment] | None = None) -> list[dict[str, Any]]:
    """Estimate median cents from finite, voiced interior frames.

    Exclude at least half a pYIN window at either boundary, plus the configured
    fractional trim. Median in log-frequency space tolerates isolated outliers;
    MAD describes spread, not confidence in alignment or octave correctness.
    Supplied alignment overrides manual timing; failed/uncertain rows never
    fall back to fixed timing and never produce an intonation measurement.
    """
    aligned = None
    if alignment is not None:
        aligned = {row.note_id: row for row in alignment}
        if len(aligned) != len(alignment) or set(aligned) != {e.id for e in events}:
            raise ValueError("Alignment must contain exactly one row per score note")
        previous_end = 0.
        for event in events:
            row = aligned[event.id]
            if row.measure != event.measure or row.expected_midi != event.midi:
                raise ValueError("Alignment does not match score")
            if row.alignment_status not in {"aligned", "uncertain", "failed"}:
                raise ValueError("Unknown alignment status")
            if row.alignment_status == "aligned":
                if (row.start_seconds is None or row.end_seconds is None
                        or not np.all(np.isfinite([row.start_seconds, row.end_seconds]))
                        or row.start_seconds < previous_end - 1e-9
                        or row.end_seconds <= row.start_seconds):
                    raise ValueError("Invalid aligned boundaries")
                previous_end = row.end_seconds
    results = []
    for event in events:
        row = aligned[event.id] if aligned is not None else None
        if row is not None and row.alignment_status != "aligned":
            results.append({**asdict(event), "start_seconds": row.start_seconds,
                            "end_seconds": row.end_seconds, "alignment_status": row.alignment_status,
                            "reference_hz": midi_to_hz(event.midi), "interior_frames": 0,
                            "valid_frames": 0, "status": "alignment_" + row.alignment_status,
                            "cents_deviation": None, "pitch_center_hz": None, "mad_cents": None})
            continue
        if row is not None:
            start = row.start_seconds
            duration = row.end_seconds - start
        else:
            start = config.start_seconds + event.onset_quarters * 60 / config.bpm
            duration = event.duration_quarters * 60 / config.bpm
        margin = max(duration * config.interior_fraction, pitch_config.frame_length / (2 * pitch_config.sample_rate))
        interior = (track.times >= start + margin) & (track.times < start + duration - margin)
        valid = (interior & track.voiced & np.isfinite(track.frequencies) & (track.frequencies > 0)
                 & np.isfinite(track.probabilities) & (track.probabilities >= config.min_voiced_probability))
        reference = midi_to_hz(event.midi)
        cents = hz_to_cents(track.frequencies[valid], reference)
        enough = len(cents) >= config.min_frames
        center = float(np.median(cents)) if enough else None
        results.append({
            **asdict(event), "alignment_status": row.alignment_status if row else "constant_tempo", "start_seconds": start, "end_seconds": start + duration,
            "reference_hz": reference, "interior_frames": int(interior.sum()),
            "valid_frames": len(cents), "status": "ok" if enough else "insufficient_frames",
            "cents_deviation": center,
            "pitch_center_hz": float(reference * 2 ** (center / 1200)) if center is not None else None,
            "mad_cents": float(np.median(np.abs(cents - center))) if center is not None else None,
        })
    return results


def write_json(path: str | Path, data: Any) -> Path:
    """Write strict JSON, converting nonfinite floats to null (never NaN tokens)."""
    def clean(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            return clean(value.tolist())
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        if isinstance(value, (float, np.floating)):
            return float(value) if np.isfinite(value) else None
        if isinstance(value, np.generic):
            return value.item()
        return value

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(clean(data), indent=2, allow_nan=False) + "\n")
    return output
