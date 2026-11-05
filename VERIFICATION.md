# Milestone 1 verification

Verified on Python 3.12.14 with `uv.lock`.

- `uv run --locked pytest -q`: **26 passed** (34.47 seconds).
- `uv build --offline`: source distribution and wheel built successfully.
- Wheel installed in a fresh Python 3.12 virtual environment; CLI demo ran
  outside the source checkout successfully.
- Default 88 BPM, seed 7, +20-cent demo: all 30 notes measured;
  maximum absolute error against synthetic input was 0.021 cents (rounded up).
- Installed-wheel 96 BPM, seed 42, -25-cent demo: all 30 notes measured;
  maximum absolute error was 0.0202 cents.
- Score roundtrip: eight complete measures, 30 notes, D major, 4/4, quarter = 88.
- Known-tone pYIN tests, FFT checks of synthesis, seeded reproducibility,
  interior-frame robustness, silence/empty input, invalid values, and strict
  JSON tests passed.

The very small demo error reflects ideal stationary signals and offsets on
pYIN's 5-cent grid; it is not a claim of sub-cent real-world accuracy. Tests
allow 8 cents for individual tones and 10 cents for the full demo.

## Failures encountered and resolved

The initial newer runtime (Numba 0.68.1, NumPy 2.5.4, SciPy 1.18.1) passed
in-process tests but segfaulted inside librosa's Numba-backed local-minimum
routine in standalone runs. Constraining to Numba 0.61.2, NumPy 2.2.6, and
SciPy 1.15.3 resolved the observed crash. The end-to-end regression now launches
a fresh Python process. No component failures remain in the verified workflow.

The environment also required writable caches and enabled dependency-download
network access. An offline wheel-install attempt could not resolve registry
metadata; an online installation into a fresh environment succeeded.

## Historical baseline scope

Milestone 1 required supplied constant BPM and recording start offset.
The automatic-alignment milestone below extends it while retaining that mode.

# Milestone 2: automatic alignment

Verified using Python 3.12.14 and the unchanged locked dependencies.
Full suite: **40 passed, 0 failed** in 263.61 seconds (26 existing tests and
14 new alignment tests). `git diff --check` also passed.

After `uv sync --frozen`, the executed test command was:

```bash
XDG_CACHE_HOME=/tmp/quartetiq-cache .venv/bin/python -m pytest -q -s
```

Equivalent reproducible command:

```bash
UV_CACHE_DIR=/tmp/quartetiq-uv-cache XDG_CACHE_HOME=/tmp/quartetiq-cache uv run --locked pytest -q -s
```

Boundary errors below compare **both starts and ends** against the unchanged
synthesizer's sample-rounded ground truth. No truth is supplied to alignment.
Each full-score case has 30 notes (60 boundaries); the local-tempo case has 12
notes (24 boundaries). All notes in these cases pass the alignment gates.

| Performance | Initial silence | Boundary MAE | Maximum absolute error |
| --- | ---: | ---: | ---: |
| 88 BPM, 0 cents | 0.25 s | 3.088 ms | 9.206 ms |
| 88 BPM, +25 cents | 2.3 s | 3.803 ms | 10.658 ms |
| 96.8 BPM (+10%), −30 cents | 0.7 s | 2.817 ms | 8.209 ms |
| 79.2 BPM (−10%), +35 cents | 0.4 s | 3.423 ms | 11.429 ms |
| Local tempo: 88 × (1 + 0.1 sin(note index)) BPM | 1.1 s | 3.534 ms | 5.488 ms |

The tests require every boundary to be within 60 ms and all measured note centers
in the constant-tempo cases to be within 10 cents of the injected deviation.
Deliberately incorrect manual BPM and offset are supplied to `analyze_notes` in
these cases to verify that automatic boundaries take precedence.

Coverage includes the full Ode to Joy repeated F#4 pairs, other repeated pitches,
internal rests, pitch-only alignment, unarticulated repeated-note uncertainty,
empty/silent/short/low-probability/wrong-pitch tracks, invalid inputs, and an
end-to-end CLI invocation using MusicXML and a WAV with unknown timing. The
original constant-tempo tests are retained unchanged.

The first alignment test run found four failures: three from floating-point
roundoff below zero in a running mean-square envelope (producing NaN RMS), and
one from computing a shared frame boundary with two slightly different floating-
point expressions. Clamping mean-square energy to zero and using the same frame
timestamp for shared boundaries resolved these numerical defects. No synthesis
code, ground truth, or boundary/intonation acceptance thresholds were changed.

Limitations: synthetic signals only, complete offline monophonic takes, no
calibrated confidence, no guaranteed handling of omitted/extra notes or partial
takes, and uncertain unisons without articulation. Background audio, strong
rubato, reverberation, or pYIN octave errors may break correspondence. Leading
score rests are indistinguishable from recording silence. See README for gates
and output semantics. No dependencies, neural models, or dashboard were added.

Files created: `src/quartetiq/alignment.py`, `tests/test_alignment.py`.
Files modified: `src/quartetiq/analysis.py`, `src/quartetiq/cli.py`, `README.md`,
`VERIFICATION.md`.

# Milestone 3: three-take rehearsal dashboard

Full suite: **70 passed, 0 failed** in 110.20 seconds, including all 40 existing
tests and 30 new comparison/dashboard tests. Executed after `uv sync --frozen`:

```bash
XDG_CACHE_HOME=/tmp/quartetiq-cache .venv/bin/python -m pytest -q
```

`git diff --check` passed.

The bundled dataset was generated with `python -m quartetiq.demo --output-dir
demo`, which writes three real WAVs and runs `analyze_file(..., auto_align=True)`
on each. Analyses include pYIN frames and alignment boundaries. Truth sidecars
are simulation inputs only; neither the dashboard nor analysis reads them.
The manifest records SHA-256 checksums of audio, analyses, and the score.

| Take | Reliable notes | Measured mean absolute error |
| --- | ---: | ---: |
| 1 | 30 / 30 | 7.35349 cents |
| 2 | 30 / 30 | 6.35349 cents |
| 3 | 30 / 30 | 1.18682 cents |

Paired first-to-last improvement is **6.16667 cents / 83.86041%**, using all 30
shared reliable note IDs. Measure 1, note 3 (G4) remains sharp at approximately
35.02, 35.02, and 30.02 cents. Measure 2, note 3 (F#4) improves from approximately
45.02 to 15.02 to 5.02 cents. The latter also meets the historical two-exceedance
rule, although its latest result is within threshold. The UI explicitly labels
this distinction. The initial demo assertion expected only one historical
recurring note; it was corrected to account for actual measured pitch resolution.
No measured values, truth, or classification threshold were changed to suppress
this observation. Measures 5–8 remain within 10 cents across all three takes.

Verification includes independent arithmetic fixtures for means, paired
improvement, percentage validity, strict persistence thresholds, stable-ID joins,
missing rows, unreliable alignment, and deterministic ranking. All five public
read-only tool functions are tested for strict JSON serialization and lack of
input mutation. Bundled results are recomputed from stored frames and one
complete WAV is independently re-analyzed through the upload service to ensure
it reproduces the bundled analysis exactly.

Streamlit AppTest covers initial demo rendering, empty upload state, an explicit
Analyze button, cache reuse, hiding stale results after file changes, and warnings
for unreliable data. Uploaded silence yields unavailable measurements. An initial
UI test stub failed to patch Streamlit's module-level uploader alias; correcting
the stub enabled the full upload interaction test without changing app behavior.
The app also started as a real local Streamlit server and its
`/_stcore/health` endpoint returned `ok`.

Added Streamlit 1.66.1 and Plotly 6.9.0 with their transitive dependencies. Comparing
the new lockfile to the previous commit found **no existing package version
changes**. In particular, NumPy 2.2.6, Numba 0.61.2, SciPy 1.15.3, librosa 0.11.0,
music21 9.9.2, and soundfile 0.13.1 are retained. A pinned pip requirements export
also installs the local package for Community Cloud compatibility.

New files: `app.py`, `src/quartetiq/comparison.py`, `src/quartetiq/dashboard.py`,
`src/quartetiq/demo.py`, `tests/test_comparison.py`, `tests/test_dashboard.py`,
`.streamlit/config.toml`, `requirements.txt`, `DEPLOYMENT.md`, and the `demo/`
score/audio/truth/analysis/manifest bundle. Modified: `src/quartetiq/synthesis.py`
(additive rehearsal generator), `pyproject.toml`, `uv.lock`, `README.md`, and this
verification report. Existing analysis/alignment implementation and 40 tests
are unchanged.

Still pending: actual Community Cloud deployment and hosted upload verification,
real microphone violin validation, real Muse Spark API/tool transport and
credentials, and the hackathon demo/submission materials. No public deployment,
real-recording accuracy, or AI conversation is claimed by this milestone.

# Milestone 4: real Meta Muse Spark integration

Full suite: **109 passed, 0 failed** in 150.97 seconds, including all 70 existing
tests plus 39 new mocked protocol/UI tests. Executed after `uv sync --frozen`:

```bash
XDG_CACHE_HOME=/tmp/quartetiq-cache .venv/bin/python -m pytest -q
```

The implementation follows Meta's official cookbook:
<https://dev.meta.ai/docs/cookbook/tool-function-calling>, inspected for this
milestone. It uses the OpenAI SDK with `https://api.meta.ai/v1`,
`muse-spark-1.3`, and explicit `MODEL_API_KEY` credentials. Only `tool_choice=
"auto"` is used, as required by the documented Meta API. No alternate model or
simulated coaching response is substituted.

## What was verified

- Five schemas match the existing comparison function signatures, with measured
  `results` bound server-side and inaccessible as model arguments.
- Explicit allowlisted dispatch, typed JSON validation, duplicate/unknown-field
  rejection, safe error tool results, full assistant-call replay, and matching
  tool-result IDs, including multiple calls and multi-round recovery.
- Every displayed coaching answer requires a successful measurement call in
  that turn. Tool-free replies and infinite loops end in a visible error within
  the bounded budget. This does not prove that every model-generated claim is
  correct; users should check recommendations against the measurements.
- Missing credentials, authentication/permission failures, network/timeout and
  quota errors, incomplete responses, and unexpected API errors yield sanitized
  messages without raw provider bodies or credentials.
- Chat rendering, history continuity, session-local storage, failure atomicity,
  reset after changed measurements/source or incomplete uploads, and a functional
  numerical dashboard when no API key is configured.
- Deployment `requirements.txt` installed successfully into a fresh Python
  3.12.14 environment at `/tmp/quartetiq-m4-deploy`; imports confirmed the local
  `quartetiq` package, Streamlit, and OpenAI SDK. OpenAI SDK version is 2.54.0.
  All previously locked package versions remain unchanged, including NumPy
  2.2.6, Numba 0.61.2, and SciPy 1.15.3. `git diff --check` passed.

## Live verification status and blockers

**Real authenticated Muse Spark request: NOT verified.** No configured key was
available in the environment or Streamlit secrets at the last check. The user
indicated they would configure a key securely; no key is stored in this commit.
An unauthenticated endpoint reachability probe failed before reaching Meta:
`CONNECT tunnel failed, response 403`. The managed workspace's restricted
network policy does not list `api.meta.ai`.

**Real model-directed tool call: NOT verified.** Mocked tests executed the actual
local read-only functions against real bundled measurements, but the model
responses in those tests were mocks. This is not evidence of live API function
calling. The code path for real calls is implemented and an explicit live smoke
test is available as `python -m quartetiq.muse --tools` after configuration.

Remaining live/deployment requirements: a valid `MODEL_API_KEY` with Muse Spark
1.3 access/quota, outbound HTTPS permission for `api.meta.ai`, successful live
connectivity plus tool-call verification, and actual Community Cloud deployment.
Community Cloud secret setup is documented in DEPLOYMENT.md. The numerical app
and deterministic priorities remain usable without these credentials.

New files: `src/quartetiq/muse.py`, `src/quartetiq/coach_ui.py`,
`tests/test_muse.py`, `tests/test_coach_ui.py`.
Modified: `app.py`, `pyproject.toml`, `uv.lock`, `requirements.txt`, `.gitignore`,
`README.md`, `DEPLOYMENT.md`, and `VERIFICATION.md`.
