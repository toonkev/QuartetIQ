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

## Next milestone

Automatic onset/score alignment and variable tempo, real microphone violin
fixtures, and validation of vibrato handling and confidence thresholds. This
baseline requires supplied constant BPM and recording start offset.
