"""Regenerate the bundled rehearsal dataset from real pYIN + DTW analysis."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import soundfile as sf

from quartetiq.analysis import AnalysisConfig, write_json
from quartetiq.cli import analyze_file
from quartetiq.pitch import PitchConfig
from quartetiq.score import generate_score, parse_score
from quartetiq.synthesis import synthesize_rehearsal_takes


def build_demo(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    score = generate_score(output / "ode_to_joy.musicxml")
    manifest = {"description": "Synthetic rehearsal demo; measurements from pYIN and automatic DTW alignment",
                "score": score.name, "takes": []}
    for take in synthesize_rehearsal_takes(parse_score(score)):
        take_id = take["take_id"]
        wav = output / f"{take_id}.wav"
        sf.write(wav, take["audio"], take["config"].sample_rate, subtype="PCM_16")
        truth = write_json(output / f"{take_id}.truth.json", {"config": asdict(take["config"]), "notes": take["truth"]})
        result_path = output / f"{take_id}.analysis.json"
        analyze_file(score, wav, result_path, PitchConfig(), AnalysisConfig(), auto_align=True)
        result = json.loads(result_path.read_text())
        result.update(take_id=take_id, score=score.name, audio=wav.name)
        write_json(result_path, result)
        manifest["takes"].append({"take_id": take_id, "audio": wav.name, "analysis": result_path.name,
                                  "truth": truth.name, "audio_sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
                                  "analysis_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()})
    manifest["score_sha256"] = hashlib.sha256(score.read_bytes()).hexdigest()
    return write_json(output / "manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("demo"))
    print(build_demo(parser.parse_args().output_dir))
