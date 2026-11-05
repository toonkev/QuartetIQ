"""Dashboard I/O, separate from read-only comparison and tool functions."""
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import soundfile as sf

from quartetiq.analysis import AnalysisConfig
from quartetiq.cli import analyze_file
from quartetiq.pitch import PitchConfig
from quartetiq.score import parse_score

MAX_AUDIO_SECONDS = 60
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def load_demo(directory: Path) -> tuple[dict, list[dict]]:
    """Load committed measured results without running audio analysis."""
    manifest = json.loads((directory / "manifest.json").read_text())
    return manifest, [json.loads((directory / take["analysis"]).read_text()) for take in manifest["takes"]]


def dataset_key(score: bytes, recordings: list[bytes]) -> str:
    """Content/order fingerprint prevents stale results after uploads change."""
    return hashlib.sha256(b"".join(hashlib.sha256(value).digest() for value in [score, *recordings])).hexdigest()


def analyze_upload(score: bytes, recording: bytes) -> dict:
    """Analyze one uploaded WAV with automatic timing and temporary local files.

    No uploads are persisted. Limits bound memory and pYIN work for this demo.
    The caller owns caching; results never contain temporary filesystem paths.
    """
    if not score or len(score) > 2 * 1024 * 1024:
        raise ValueError("Choose a MusicXML file smaller than 2 MB")
    if not recording or len(recording) > MAX_UPLOAD_BYTES:
        raise ValueError("Each WAV must be nonempty and smaller than 20 MB")
    try:
        info = sf.info(io.BytesIO(recording))
    except (RuntimeError, ValueError) as exc:
        raise ValueError("This recording could not be read as WAV audio") from exc
    if info.format not in {"WAV", "WAVEX"} or not 0 < info.duration <= MAX_AUDIO_SECONDS or info.channels > 2:
        raise ValueError("Use mono or stereo WAV recordings up to 60 seconds long")
    with TemporaryDirectory(prefix="quartetiq-") as folder:
        root = Path(folder)
        xml, wav, output = root / "score.musicxml", root / "take.wav", root / "result.json"
        xml.write_bytes(score)
        wav.write_bytes(recording)
        try:
            events = parse_score(xml)
        except Exception as exc:
            raise ValueError("The score must be valid MusicXML with one monophonic part") from exc
        if len(events) > 120:
            raise ValueError("Please select a passage of at most 120 notes")
        analyze_file(xml, wav, output, PitchConfig(), AnalysisConfig(), auto_align=True)
        result = json.loads(output.read_text())
        result.update(score="uploaded_score.musicxml", audio="uploaded_take.wav")
        return result
