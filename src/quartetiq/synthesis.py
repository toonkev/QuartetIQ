"""Deterministic harmonic violin-like fixtures, not a physical violin model."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.signal.windows import tukey

from quartetiq.pitch import FloatArray, midi_to_hz
from quartetiq.score import NoteEvent


@dataclass(frozen=True)
class SynthesisConfig:
    """Constant quarter-note BPM, pitch offset, vibrato, and seeded noise."""

    sample_rate: int = 22050
    bpm: float = 88.0
    start_seconds: float = 0.25
    cents: float = 0.0
    vibrato_cents: float = 0.0
    vibrato_hz: float = 5.5
    noise_std: float = 0.0005
    seed: int = 0

    def __post_init__(self) -> None:
        if not all(np.isfinite(v) for v in (self.bpm, self.start_seconds, self.cents, self.vibrato_cents, self.vibrato_hz, self.noise_std)):
            raise ValueError("Synthesis parameters must be finite")
        if self.sample_rate <= 0 or self.bpm <= 0 or min(self.start_seconds, self.vibrato_cents, self.vibrato_hz, self.noise_std) < 0:
            raise ValueError("Invalid synthesis timing or noise/vibrato parameters")


def synthesize(events: Sequence[NoteEvent], config: SynthesisConfig = SynthesisConfig(),
               note_cents: Mapping[str, float] | None = None) -> tuple[FloatArray, list[dict[str, str | float]]]:
    """Return mono audio and separate ground truth; per-note cents override global.

    Harmonics above Nyquist are omitted. Notes have tapered attacks/releases,
    with silence before and after. Timing is rounded to the nearest sample.
    """
    overrides = note_cents or {}
    if set(overrides) - {event.id for event in events}:
        raise ValueError("Pitch override references unknown note ID")
    seconds_per_quarter = 60 / config.bpm
    end = max((e.onset_quarters + e.duration_quarters for e in events), default=0)
    audio = np.zeros(round((config.start_seconds + end * seconds_per_quarter + .25) * config.sample_rate))
    rng = np.random.default_rng(config.seed)
    truth: list[dict[str, str | float]] = []
    for event in events:
        cents = float(overrides.get(event.id, config.cents))
        if not np.isfinite(cents):
            raise ValueError("Pitch offsets must be finite")
        hz = midi_to_hz(event.midi + cents / 100)
        if hz * 2 ** (config.vibrato_cents / 1200) >= config.sample_rate / 2:
            raise ValueError("Synthesized frequency exceeds Nyquist")
        start = config.start_seconds + event.onset_quarters * seconds_per_quarter
        stop = start + event.duration_quarters * seconds_per_quarter
        first, last = round(start * config.sample_rate), round(stop * config.sample_rate)
        if first < 0 or last <= first:
            raise ValueError("Note must have nonnegative onset and positive sample duration")
        t = np.arange(last - first) / config.sample_rate
        instantaneous_hz = hz * np.exp2(config.vibrato_cents * np.sin(2 * np.pi * config.vibrato_hz * t) / 1200)
        phase = 2 * np.pi * np.cumsum(instantaneous_hz) / config.sample_rate
        signal = np.zeros(len(t))
        for harmonic in range(1, 9):
            if harmonic * np.max(instantaneous_hz) < config.sample_rate / 2:
                signal += np.sin(harmonic * phase) / harmonic ** 1.3
        signal = .35 * signal + rng.normal(0, config.noise_std, len(t))
        audio[first:last] += signal * tukey(len(t), alpha=.16)
        truth.append({"id": event.id, "start_seconds": first / config.sample_rate,
                      "end_seconds": last / config.sample_rate, "frequency_hz": hz, "cents": cents})
    if np.max(np.abs(audio), initial=0) > 1:
        raise ValueError("Synthetic signal clips; reduce noise")
    return audio, truth


def synthesize_rehearsal_takes(events: Sequence[NoteEvent]) -> list[dict]:
    """Three reproducible rehearsal recordings with explicit per-note truth.

    Note 3 stays sharp; note 7 improves; all other notes are near equal temperament.
    Uses the existing synthesizer unchanged and varies tempo/initial silence.
    """
    if len(events) < 7:
        raise ValueError("The rehearsal demo requires at least seven notes")
    takes = []
    for i, (bpm, start, accurate, sharp, improving) in enumerate([
        (88., .25, 5., 35., 45.), (92., .7, 3., 33., 12.), (84., 1.1, 0., 31., 3.)
    ], 1):
        config = SynthesisConfig(bpm=bpm, start_seconds=start, seed=i)
        deviations = {e.id: accurate for e in events}
        deviations[events[2].id] = sharp
        deviations[events[6].id] = improving
        audio, truth = synthesize(events, config, deviations)
        takes.append({"take_id": f"take_{i}", "config": config, "audio": audio, "truth": truth})
    return takes
