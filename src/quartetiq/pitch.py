"""Equal-tempered pitch conversion and measured pYIN frame extraction."""

from dataclasses import dataclass

import librosa
import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def midi_to_hz(midi: float) -> float:
    """Convert MIDI pitch to Hz using A4 (MIDI 69) = 440 Hz."""
    if not np.isfinite(midi):
        raise ValueError("MIDI pitch must be finite")
    frequency = float(440.0 * np.exp2((midi - 69.0) / 12.0))
    if not np.isfinite(frequency) or frequency <= 0:
        raise ValueError("MIDI pitch is outside representable frequencies")
    return frequency


def hz_to_cents(frequency: float | FloatArray, reference_hz: float = 440.0) -> FloatArray:
    """Return 1200 log2(f/reference); invalid measured frequencies become NaN."""
    if not np.isfinite(reference_hz) or reference_hz <= 0:
        raise ValueError("Reference frequency must be finite and positive")
    values = np.asarray(frequency, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(np.isfinite(values) & (values > 0), 1200 * (np.log2(values) - np.log2(reference_hz)), np.nan)


@dataclass(frozen=True)
class PitchConfig:
    """pYIN settings; resolution is in semitones (0.05 = 5 cents)."""

    sample_rate: int = 22050
    frame_length: int = 2048
    hop_length: int = 256
    fmin: float = 196.0
    fmax: float = 1200.0
    resolution: float = 0.05

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.frame_length < 4 or not 0 < self.hop_length <= self.frame_length:
            raise ValueError("Invalid sample rate, frame length, or hop length")
        if not 0 < self.fmin < self.fmax < self.sample_rate / 2:
            raise ValueError("Require 0 < fmin < fmax < Nyquist")
        if not np.isfinite(self.resolution) or not 0 < self.resolution <= 1:
            raise ValueError("Resolution must be in (0, 1]")
        if self.sample_rate / self.fmin >= self.frame_length - 1:
            raise ValueError("Frame length is too short for fmin")


@dataclass(frozen=True)
class PitchTrack:
    """Centered frame timestamps, measured Hz, voicing flags, and probabilities."""

    times: FloatArray
    frequencies: FloatArray
    voiced: NDArray[np.bool_]
    probabilities: FloatArray


def estimate_pitch(audio: FloatArray, config: PitchConfig = PitchConfig()) -> PitchTrack:
    """Measure mono audio at config.sample_rate with librosa pYIN.

    Nonfinite input samples are rejected; empty input yields an empty track.
    Unvoiced frequencies are NaN internally and become null in JSON output.
    """
    samples = np.asarray(audio, dtype=float)
    if samples.ndim != 1 or not np.all(np.isfinite(samples)):
        raise ValueError("Audio must be finite and mono")
    if samples.size == 0:
        return PitchTrack(np.array([]), np.array([]), np.array([], dtype=bool), np.array([]))
    f0, voiced, probability = librosa.pyin(
        samples, sr=config.sample_rate, fmin=config.fmin, fmax=config.fmax,
        frame_length=config.frame_length, hop_length=config.hop_length,
        resolution=config.resolution, fill_na=np.nan, center=True,
    )
    times = librosa.frames_to_time(np.arange(len(f0)), sr=config.sample_rate, hop_length=config.hop_length)
    return PitchTrack(times, f0, voiced, probability)
