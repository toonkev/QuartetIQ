"""Command-line entry points for independent steps and the baseline demo."""

import argparse
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from quartetiq.analysis import AnalysisConfig, analyze_notes, write_json
from quartetiq.pitch import PitchConfig, estimate_pitch
from quartetiq.score import generate_score, parse_score
from quartetiq.synthesis import SynthesisConfig, synthesize


def analyze_file(score: Path, audio: Path, output: Path, pitch: PitchConfig,
                 analysis: AnalysisConfig) -> Path:
    """Read WAV/audio, downmix/resample, measure F0, and save provenance + frames."""
    samples, source_rate = sf.read(audio, dtype="float64", always_2d=True)
    if not np.all(np.isfinite(samples)):
        raise ValueError("Audio contains nonfinite samples")
    mono = samples.mean(axis=1)
    if source_rate != pitch.sample_rate and mono.size:
        mono = librosa.resample(mono, orig_sr=source_rate, target_sr=pitch.sample_rate)
    events = parse_score(score)
    track = estimate_pitch(mono, pitch)
    return write_json(output, {
        "schema_version": 1, "score": str(score), "audio": str(audio),
        "alignment": "known constant tempo and start offset; no automatic alignment",
        "tuning": {"a4_hz": 440.0, "temperament": "12-tone equal"},
        "versions": {name: version(name) for name in ("quartetiq", "librosa", "numpy", "scipy", "music21", "soundfile")},
        "pitch_config": asdict(pitch), "analysis_config": asdict(analysis),
        "notes": analyze_notes(events, track, pitch, analysis),
        "frames": {"time_seconds": track.times, "frequency_hz": track.frequencies,
                   "voiced": track.voiced, "voiced_probability": track.probabilities},
    })


def main() -> None:
    """Run score, synthesize, analyze, or demo; see --help for parameters."""
    parser = argparse.ArgumentParser(description="QuartetIQ solo-violin analysis baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    score_parser = commands.add_parser("score", help="Generate the eight-measure MusicXML")
    score_parser.add_argument("output", type=Path)
    for name in ("synthesize", "analyze", "demo"):
        sub = commands.add_parser(name)
        if name == "demo":
            sub.add_argument("--output-dir", type=Path, default=Path("artifacts/baseline"))
        else:
            sub.add_argument("score", type=Path)
            sub.add_argument("audio", type=Path)
        sub.add_argument("--bpm", type=float, default=88)
        sub.add_argument("--start-seconds", type=float, default=.25)
        sub.add_argument("--sample-rate", type=int, default=22050)
        if name in ("synthesize", "demo"):
            sub.add_argument("--cents", type=float, default=0)
            sub.add_argument("--vibrato-cents", type=float, default=0)
            sub.add_argument("--noise-std", type=float, default=.0005)
            sub.add_argument("--seed", type=int, default=0)
        if name in ("analyze", "demo"):
            if name == "analyze":
                sub.add_argument("--output", type=Path, default=Path("artifacts/analysis.json"))
            sub.add_argument("--fmin", type=float, default=196)
            sub.add_argument("--fmax", type=float, default=1200)
            sub.add_argument("--frame-length", type=int, default=2048)
            sub.add_argument("--hop-length", type=int, default=256)
            sub.add_argument("--resolution", type=float, default=.05)
            sub.add_argument("--interior-fraction", type=float, default=.15)
            sub.add_argument("--min-voiced-probability", type=float, default=.8)
            sub.add_argument("--min-frames", type=int, default=5)
    args = parser.parse_args()
    try:
        if args.command == "score":
            print(generate_score(args.output))
            return
        if args.command == "demo":
            args.score = generate_score(args.output_dir / "ode_to_joy.musicxml")
            args.audio = args.output_dir / "synthetic.wav"
            args.output = args.output_dir / "analysis.json"
        if args.command in ("synthesize", "demo"):
            config = SynthesisConfig(sample_rate=args.sample_rate, bpm=args.bpm,
                                     start_seconds=args.start_seconds, cents=args.cents,
                                     vibrato_cents=args.vibrato_cents, noise_std=args.noise_std, seed=args.seed)
            samples, truth = synthesize(parse_score(args.score), config)
            args.audio.parent.mkdir(parents=True, exist_ok=True)
            sf.write(args.audio, samples, config.sample_rate, subtype="FLOAT")
            write_json(args.audio.with_suffix(".truth.json"), {"config": asdict(config), "notes": truth})
            print(args.audio)
        if args.command in ("analyze", "demo"):
            pitch = PitchConfig(args.sample_rate, args.frame_length, args.hop_length, args.fmin, args.fmax, args.resolution)
            analysis = AnalysisConfig(args.bpm, args.start_seconds, args.interior_fraction, args.min_voiced_probability, args.min_frames)
            print(analyze_file(args.score, args.audio, args.output, pitch, analysis))
    except (ValueError, OSError) as error:
        parser.error(str(error))
