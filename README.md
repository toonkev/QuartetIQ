# QuartetIQ

A Python 3.12 numerical baseline for solo-violin intonation analysis. Generates
an eight-bar Ode to Joy arrangement in D major (4/4, quarter = 88), synthesizes
controlled harmonic audio, measures F0 with librosa pYIN, and compares median
note pitch centers to A4 = 440 Hz equal temperament. No UI dependency.

## Install and run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
cd /workspace/QuartetIQ  # or your checkout location
uv sync --locked
uv run pytest
uv run quartetiq demo --output-dir artifacts/baseline --cents 20 --seed 7
```

`uv.lock` pins dependencies. `.python-version` selects Python 3.12; uv can install
it if necessary. First pYIN execution may take longer due to Numba compilation.
NumPy 2.2, SciPy 1.15, and Numba 0.61 are constrained to the verified runtime
line: the initially resolved newer runtime crashed inside pYIN in a fresh process.
The CLI regression test runs in a subprocess to exercise this boundary.

In a sandbox with a read-only home directory, use writable caches:

```bash
export UV_CACHE_DIR=/tmp/quartetiq-uv-cache
export XDG_CACHE_HOME=/tmp/quartetiq-cache
```

The demo writes `ode_to_joy.musicxml`, `synthetic.wav`, `synthetic.truth.json`,
and `analysis.json`. The truth sidecar contains simulation inputs, while analysis
contains actual measured frames and note centers; analysis never reads truth.
Repeat runs with identical synthesis settings and locked dependencies produce
identical audio samples. MusicXML exporter metadata need not be byte-identical.

Run the steps independently:

```bash
uv run quartetiq score artifacts/ode.musicxml
uv run quartetiq synthesize artifacts/ode.musicxml artifacts/test.wav --bpm 96 --cents -25 --seed 42
uv run quartetiq analyze artifacts/ode.musicxml artifacts/test.wav --bpm 96 --output artifacts/result.json
```

Use `uv run quartetiq demo --help` for pitch range, frame/hop lengths, pYIN
resolution, confidence threshold, interior trim, minimum frames, sample rate,
tempo, recording offset, noise, and vibrato settings. Synthesis additionally
supports per-note cents overrides through its Python API. Defaults use 22,050 Hz,
2048-sample windows, 256-sample hops, 196–1200 Hz, and 5-cent pYIN resolution.

## Interfaces and result semantics

- `score.py`: `generate_score(path)` and `parse_score(path)` return stable written
  note events. IDs use part/measure/note ordinals, not memory addresses. Beats
  are 1-based; onset/duration are quarter-note units. Rests produce timing gaps.
- `synthesis.py`: `synthesize(events, config, note_cents)` returns mono audio and
  separate ground truth. Eight decaying harmonics, tapered envelopes, optional
  vibrato, and seeded noise approximate violin-like test signals.
- `pitch.py`: `estimate_pitch(audio, config)` returns centered frame timestamps,
  Hz, voicing, and probabilities. Input must be finite mono audio at the specified
  sample rate. Empty audio returns no frames; silence yields unavailable F0.
- `analysis.py`: `analyze_notes(events, track, pitch_config, config)` takes the
  median cents of finite positive voiced interior frames above the probability
  threshold. Trim is the larger of 15% of duration or half an analysis window at
  each edge. At least five valid frames are required. MAD reports pitch spread.
- `cli.py`: `analyze_file` loads audio, downmixes stereo, resamples if needed,
  and persists measured frames, note results, parameters, and dependency versions.

Cents are `1200 * log2(measured_hz / score_hz)`: positive is sharp, negative is
flat. JSON schema version 1 stores unavailable numeric results as `null`, never
nonstandard NaN or Infinity. `insufficient_frames` explicitly identifies missing
measurements. Invalid audio samples and invalid configuration raise errors.

## Automatic alignment

Use automatic alignment without supplying performance BPM or start time:

```bash
uv run quartetiq analyze artifacts/ode.musicxml artifacts/test.wav --auto-align --output artifacts/aligned.json
```

The default constant-tempo mode remains available. `--auto-align` on `demo`
uses BPM/start only for synthesis; alignment receives neither parameter.
Automatic output uses schema version 2 and includes `note_alignment` rows with
`note_id`, `measure`, `expected_midi`, `start_seconds`, `end_seconds`, and
`alignment_status`. The Python API is `align_notes(events, track, audio,
pitch_config)`, followed by `analyze_notes(..., alignment=alignment)`.
Audio is optional but supplies evidence for repeated-note articulation.

The aligner infers global tempo from the active recording span and score duration,
then uses segmental DTW: each note or rest consumes a contiguous run of pitch
frames. Pitch mismatch, duration deviation, and short-window amplitude valleys
score transitions. Local durations are constrained to 65–140% of the inferred
average, with a cumulative timing band. This accommodates ±10% tempo changes
and moderate local variation. Initial/final silence is trimmed; internal score
rests are explicit states. No ground-truth sidecar or score BPM is read.

`aligned` means the path passed evidence gates, not a calibrated probability.
A note needs at least five voiced interior frames, at least 50% interior voicing,
and median pitch mismatch no larger than 75 cents. Repeated adjacent pitches
need acoustic boundary evidence; otherwise both notes become `uncertain`.
Widespread pitch mismatch (over 20% of notes), insufficient audio, or no feasible
path produces `failed` rows. Unavailable boundaries are null. Uncertain/failed
rows produce null intonation, never a fallback measurement at a fixed time.
Aligned rows use robust median cents over the trimmed aligned interval.

### Current limitations

This is offline alignment of a complete, single-part monophonic take. Missing or
extra notes, restarts, partial takes, large rubato, strong background sounds,
long reverberation, and octave tracking errors are unsupported and can cause
failure or incorrect correspondence. Gates are conservative heuristics; they do
not detect every wrong path. Slurred repeated pitches without a detectable
amplitude dip are intentionally uncertain; tied written segments have the same
limitation. Quiet attacks/releases introduce frame/window-scale boundary error.
Leading score rests cannot be distinguished from recording silence.

The parser rejects chords, overlapping voices, and grace notes; repeats are not
expanded. Synthetic validation does not establish microphone violin accuracy.
Real-recording fixtures, calibrated reliability, vibrato-aware diagnostics, and
cross-take analysis remain future work. No dashboard or model retraining is part
of this milestone.
