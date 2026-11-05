# QuartetIQ

A Python 3.12 numerical baseline for solo-violin intonation analysis. Generates
an eight-bar Ode to Joy arrangement in D major (4/4, quarter = 88), synthesizes
controlled harmonic audio, measures F0 with librosa pYIN, and compares median
note pitch centers to A4 = 440 Hz equal temperament. A Streamlit rehearsal
dashboard compares three takes using actual measured results.

## Install and run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
cd /workspace/QuartetIQ  # or your checkout location
uv sync --locked
uv run pytest
uv run streamlit run app.py
# Optional numerical demo:
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
Real-recording fixtures, calibrated reliability, and vibrato-aware diagnostics
remain future work. The dashboard below adds cross-take analysis without model
retraining.

## Rehearsal dashboard

Run `uv run streamlit run app.py` from the repository root. The bundled Ode to Joy
session appears immediately: no audio analysis runs on initial demo load. Listen
to the three recordings, view take averages and the signed-error plot, inspect
note/measure tables, and download the measured comparison as strict JSON.

Choose **Upload my recordings**, select one `.musicxml`/`.xml` score and three
WAVs in chronological order, then click **Analyze recordings**. Each recording
uses automatic alignment without supplied BPM/start time. Uploads are limited to
20 MB, mono/stereo WAV, 60 seconds each, and 120 score notes. Three complete
recordings of the same monophonic passage are required. Uncertain alignment or
unavailable pitch produces a warning and blank measurement, never zero error.
Changing an upload hides old results until analysis completes.

pYIN is CPU-intensive and first-run JIT compilation adds startup time. Uploaded
audio is processed server-side in temporary files deleted after analysis.
`st.cache_data` caches by exact score/audio bytes, up to nine analyses for one
hour in server memory; it avoids recomputing unchanged takes on reruns. The cache
is shared within the server process; raw upload bytes participate in cache keys,
and each visitor's upload/results state is session-local. There is no database,
authentication, or long-term upload storage in this milestone.

### Comparison semantics

`comparison.py` joins notes by stable score IDs, validates matching score
metadata, and excludes nonfinite values, non-OK pitch measurements, and
uncertain/failed/unknown alignment. Explicit constant-tempo results remain
supported. Take means are unweighted means across reliable notes; coverage is
always reported. Signed cents retain sharp/flat direction; absolute cents
measure magnitude.

First-to-last improvement uses **only shared reliable notes**, so missing data
cannot masquerade as improvement. Positive improvement is reduced absolute
error; negative improvement is worsening. Percentage reduction is null when
there are no paired notes or the initial mean error is zero.

A persistent error exceeds the provisional **15-cent** threshold in at least
two reliable takes. Two observed exceedances suffice if the third measurement
is unavailable; counts and coverage remain visible. Fewer than two reliable
observations yield `insufficient_data`. A value exactly 15 does not exceed it.
Priorities rank recurring notes first, then known latest errors ahead of
unavailable latest measurements, then descending latest/mean absolute error,
and finally stable ID. A note that has improved can still have a recurring
history; the dashboard explicitly marks when its latest take is within threshold.

### Bundled demo provenance

`demo/` contains the score, three WAVs, truth sidecars, measured analyses (including
pYIN frames and automatic boundaries), and a SHA-256 manifest. Regenerate with:

```bash
uv run python -m quartetiq.demo --output-dir demo
```

The existing synthesizer is reused with deterministic per-note deviations:

| Pattern | Note | Synthesis targets, takes 1 → 3 |
| --- | --- | --- |
| Stays sharp | Measure 1, note 3, G4 | +35, +33, +31 cents |
| Improves | Measure 2, note 3, F#4 | +45, +12, +3 cents |
| Accurate passage | All other notes, including measures 5–8 | +5, +3, 0 cents |

Tempo is 88/92/84 BPM with 0.25/0.7/1.1-second initial silence. Analysis reads the
written WAVs and never reads truth sidecars. UI results are loaded exclusively
from measured analysis files. The improving note's middle take measures about
15.02 cents (pYIN has finite pitch resolution), so the strict measured threshold
also flags its history as recurring; its last take measures about 5.02 cents.
We retain this real result rather than alter truth or override classification.
Synthetic results do not establish accuracy on real microphone recordings.

### Read-only functions for Muse Spark integration

The public functions in `quartetiq.comparison` are:

- `get_performance_summary(results, threshold_cents=15.0)` — take means, coverage,
  and paired first-to-last improvement.
- `compare_takes(results, threshold_cents=15.0)` — complete comparison, including
  signed/absolute observations and exclusion reasons per note.
- `get_measure_analysis(results, measure=None, threshold_cents=15.0)` — all
  measure summaries, optionally filtered by integer measure number.
- `get_persistent_errors(results, threshold_cents=15.0)` — recurring notes with
  observation counts, actual measurements, and improvement.
- `get_practice_priorities(results, threshold_cents=15.0)` — deterministic ranks
  and evidence; no generated advice.

`results` is a chronological list of QuartetIQ analysis dictionaries, each with
`notes` and optional unique `take_id` (defaults to `take_1`, etc.). Outputs contain
only JSON-compatible dictionaries/lists/scalars/null, support
`json.dumps(output, allow_nan=False)`, and never mutate inputs or perform I/O.
Invalid or conflicting score metadata raises `ValueError`. The future Muse Spark
adapter can bind a verified session's results and expose these named functions
as read-only tools; no API credentials, model calls, or simulated conversations
are included here.

See [DEPLOYMENT.md](DEPLOYMENT.md) for Streamlit Community Cloud setup and
[VERIFICATION.md](VERIFICATION.md) for measured results and tests.

### Before hackathon submission

- Deploy to Community Cloud and verify its public URL and upload flow there.
- Validate with real solo-violin recordings, particularly repeated/slurred notes
  and noisy rooms; document cases with unreliable correspondence.
- Connect the real Muse Spark API/tool transport, obtain credentials, and test
  grounded responses, errors, and session isolation. The current app has no AI chat.
- Record the short demo and prepare the submission narrative, repository link,
  and measured limitations. Confirm the event's submission/API requirements.
- Before broader public use, add authentication/resource controls appropriate
  to the audience and validate concurrent upload performance on the deployment.
