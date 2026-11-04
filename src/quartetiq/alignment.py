"""Offline, duration-constrained (segmental) DTW for complete monophonic takes.

Each score note/rest consumes a contiguous run of pYIN frames. Duration bounds
constrain the DTW slope; pitch costs, duration costs and acoustic boundaries
choose the path. No synthesis metadata, BPM, or recording offset is used.
Statuses are evidence-based gates, not calibrated confidence probabilities.
"""
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from quartetiq.pitch import PitchConfig, PitchTrack
from quartetiq.score import NoteEvent


@dataclass(frozen=True)
class NoteAlignment:
    note_id: str
    measure: int
    expected_midi: float
    start_seconds: float | None
    end_seconds: float | None
    alignment_status: str


def align_notes(events: Sequence[NoteEvent], track: PitchTrack,
                audio: np.ndarray | None = None,
                pitch_config: PitchConfig = PitchConfig()) -> list[NoteAlignment]:
    """Align a complete take, allowing local durations 65–140% of inferred tempo.

    Global tempo is inferred from the active span and score length. Initial and
    final silence are excluded. Optional mono audio at pitch_config.sample_rate
    supplies amplitude valleys for rearticulated unisons. Without such evidence,
    adjacent unisons are uncertain. Unsupported omissions/extras or bad pitch
    correspondence fail conservatively. Leading score rests are unobservable.
    """
    def failed(status="failed"):
        return [NoteAlignment(e.id, e.measure, e.midi, None, None, status) for e in events]

    if not events:
        return []
    previous = -1.0
    for e in events:
        if (not np.all(np.isfinite([e.onset_quarters, e.duration_quarters, e.midi]))
                or e.onset_quarters < max(0, previous) - 1e-9 or e.duration_quarters <= 0):
            raise ValueError("Alignment requires ordered, nonoverlapping positive-duration notes")
        previous = e.onset_quarters + e.duration_quarters
    if len({e.id for e in events}) != len(events):
        raise ValueError("Note IDs must be unique")
    times = np.asarray(track.times)
    if any(np.asarray(v).shape != times.shape for v in (track.frequencies, track.voiced, track.probabilities)) or times.ndim != 1:
        raise ValueError("Pitch track arrays must have matching one-dimensional shapes")
    if len(times) < 2:
        return failed()
    dt = float(np.median(np.diff(times)))
    if not np.all(np.isfinite(times)) or times[0] < 0 or dt <= 0 or not np.allclose(np.diff(times), dt):
        raise ValueError("Alignment requires finite, uniformly increasing frame times")
    valid = (track.voiced & np.isfinite(track.frequencies) & (track.frequencies > 0)
             & np.isfinite(track.probabilities) & (track.probabilities >= .5))
    if valid.sum() < 5:
        return failed()
    midi = np.full(len(times), np.nan)
    midi[valid] = 69 + 12 * np.log2(track.frequencies[valid] / 440)
    boundary = np.zeros(len(times) + 1)
    active = np.flatnonzero(valid)
    first, last = int(active[0]), int(active[-1] + 1)
    if audio is not None:
        samples = np.asarray(audio, dtype=float)
        if samples.ndim != 1 or not np.all(np.isfinite(samples)):
            raise ValueError("Audio must be finite and mono")
        if len(samples) == 0 or times[-1] > len(samples) / pitch_config.sample_rate + dt:
            raise ValueError("Audio and pitch track duration do not agree")
        # Short RMS windows preserve rearticulation dips blurred by pYIN windows.
        # Running sums can drift a few ulps below zero in exact silence.
        power = uniform_filter1d(samples ** 2, max(1, round(.012 * pitch_config.sample_rate)))
        rms = np.sqrt(np.maximum(power, 0.))
        energy = np.interp(times, np.arange(len(samples)) / pitch_config.sample_rate, rms)
        level = float(np.percentile(energy[valid], 75))
        if level > 0:
            sounding = np.flatnonzero(energy > .025 * level)
            if len(sounding):
                first, last = int(sounding[0]), min(len(times), int(sounding[-1] + 1))
            valleys, props = find_peaks(-energy, prominence=.35 * level, distance=max(1, round(.10 / dt)))
            for k, prominence in zip(valleys, props["prominences"]):
                boundary[k] = min(1., prominence / level)
    if last - first < 5 * len(events):
        return failed()
    # Insert explicit rest states, preserving score timing gaps.
    states = []
    origin = events[0].onset_quarters
    cursor = origin
    for i, e in enumerate(events):
        if e.onset_quarters > cursor + 1e-9:
            states.append((None, e.onset_quarters - cursor))
        states.append((i, e.duration_quarters))
        cursor = e.onset_quarters + e.duration_quarters
    scale = (last - first) / (cursor - origin)
    count = last - first
    dp = np.full(count + 1, np.inf)
    dp[0] = 0
    parents = []
    elapsed = 0.
    for index, quarters in states:
        expected = quarters * scale
        low, high = max(2, int(expected * .65)), max(2, int(np.ceil(expected * 1.4)))
        if index is None:
            cost = np.where(valid[first:last], 2., 0.)
        else:
            # A 25–40 cent error is not grounds to relabel a note.
            distance = np.abs(midi[first:last] - events[index].midi)
            cost = np.where(valid[first:last], np.minimum(distance, 3.), .8)
        cumulative = np.r_[0., np.cumsum(cost)]
        nxt = np.full(count + 1, np.inf)
        parent = np.full(count + 1, -1, dtype=int)
        elapsed += expected
        band = max(2 * scale, .15 * count)
        for stop in range(max(low, int(elapsed - band)), min(count, int(elapsed + band)) + 1):
            starts = np.arange(max(0, stop - high), stop - low + 1)
            if not len(starts):
                continue
            durations = stop - starts
            values = (dp[starts] + cumulative[stop] - cumulative[starts]
                      + .25 * expected * ((durations / expected - 1) / .25) ** 2)
            if index is not None:
                values -= .35 * min(expected, scale) * boundary[first + starts]
            best = int(np.argmin(values))
            nxt[stop], parent[stop] = values[best], starts[best]
        dp = nxt
        parents.append(parent)
    if not np.isfinite(dp[count]):
        return failed()
    spans = {}
    stop = count
    for (index, _), parent in zip(reversed(states), reversed(parents)):
        start = int(parent[stop])
        if index is not None:
            spans[index] = (first + start, first + stop)
        stop = start
    statuses = ["aligned"] * len(events)
    for i, e in enumerate(events):
        a, b = spans[i]
        trim = max(1, int((b - a) * .15))
        observed = midi[a + trim:b - trim]
        finite = observed[np.isfinite(observed)]
        if len(finite) < 5 or len(finite) < .5 * len(observed):
            statuses[i] = "uncertain"
        elif np.median(np.abs(finite - e.midi)) > .75:
            statuses[i] = "failed"
        if i and e.midi == events[i - 1].midi and abs(e.onset_quarters - (events[i - 1].onset_quarters + events[i - 1].duration_quarters)) < 1e-9:
            if np.max(boundary[max(0, a - 2):a + 3], initial=0) < .35:
                for j in (i - 1, i):
                    if statuses[j] != "failed":
                        statuses[j] = "uncertain"
    # Widespread mismatch invalidates the correspondence of the whole take.
    if statuses.count("failed") > .2 * len(events):
        return failed()
    return [NoteAlignment(e.id, e.measure, e.midi,
                          float(times[spans[i][0]]),
                          float(times[spans[i][1]] if spans[i][1] < len(times) else times[-1] + dt), statuses[i])
            for i, e in enumerate(events)]
