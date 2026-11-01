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

## Baseline scope and next milestone

Timing is **provided**, not inferred: analysis BPM and start offset must match
performance timing. No rubato, onset detection, time warping, or automatic score
following is implemented. Median centers resist isolated frame errors but do not
correct sustained octave errors or wrong alignment. Synthetic accuracy does not
establish accuracy on microphone recordings.

The parser supports one monophonic part; chords, overlapping voices, and grace
notes are rejected. Repeats are not expanded; tied written segments remain separate
events. The generated arrangement needs neither repeats nor ties. Future work:
real violin fixtures, automatic note alignment, vibrato-aware diagnostics, and
validation of confidence and error thresholds on real performances.
