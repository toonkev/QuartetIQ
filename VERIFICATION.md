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
