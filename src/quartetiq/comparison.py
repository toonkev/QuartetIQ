"""Read-only, JSON-serializable rehearsal comparisons for UI and future tools.

Inputs are QuartetIQ analysis dictionaries in chronological take order. IDs are
stable score IDs, never row positions. Positive improvement means lower absolute
error. Missing observations remain null; aggregate changes use paired notes.
"""
from collections.abc import Mapping, Sequence
import math
from statistics import mean
from typing import Any

THRESHOLD_CENTS = 15.0


def _mean(values):
    return float(mean(values)) if values else None


def _measurement(row):
    if row is None:
        return None, "missing_note"
    if row.get("status") != "ok":
        return None, row.get("status") or "missing_status"
    if row.get("alignment_status") not in {"aligned", "constant_tempo"}:
        return None, row.get("alignment_status") or "unknown_alignment"
    value = row.get("cents_deviation")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None, "unavailable_pitch"
    return float(value), None


def compare_takes(results: Sequence[Mapping[str, Any]],
                  threshold_cents: float = THRESHOLD_CENTS) -> dict[str, Any]:
    """Compare any number of takes of the same score (normally three).

    Persistence requires two reliable observations exceeding the provisional
    threshold, even if the third is unavailable. This is a count, not confidence.
    Constant-tempo measurements are accepted only when explicitly so labelled.
    Duplicate IDs and conflicting score metadata raise ValueError. Callers must
    supply analyses of the same score; structurally identical passages cannot be
    distinguished from IDs alone. No input is modified and no files are read.
    """
    if not results:
        raise ValueError("At least one analysis result is required")
    if not math.isfinite(threshold_cents) or threshold_cents <= 0:
        raise ValueError("Threshold must be finite and positive")
    takes, score, take_ids = [], {}, set()
    fields = ("measure", "pitch", "midi", "onset_quarters", "duration_quarters")
    for i, result in enumerate(results):
        take_id = result.get("take_id", f"take_{i + 1}")
        if not isinstance(take_id, str) or not take_id or take_id in take_ids:
            raise ValueError("Take IDs must be unique nonempty strings")
        take_ids.add(take_id)
        rows = result.get("notes")
        if not isinstance(rows, list):
            raise ValueError("Each analysis must contain a notes list")
        indexed = {}
        for row in rows:
            note_id = row.get("id")
            if not isinstance(note_id, str) or not note_id or note_id in indexed:
                raise ValueError("Score note IDs must be unique nonempty strings within each take")
            metadata = {field: row.get(field) for field in fields}
            if not isinstance(metadata["measure"], int):
                raise ValueError("Each note requires an integer measure")
            for field in ("midi", "onset_quarters", "duration_quarters"):
                value = metadata[field]
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"Each note requires finite {field}")
            if not isinstance(metadata["pitch"], str):
                raise ValueError("Each note requires a pitch name")
            if note_id in score and score[note_id] != metadata:
                raise ValueError(f"Conflicting score metadata for {note_id}")
            score[note_id] = metadata
            indexed[note_id] = row
        takes.append((take_id, indexed))
    notes = []
    for note_id in sorted(score, key=lambda key: (score[key]["onset_quarters"], key)):
        observations = []
        for take_id, rows in takes:
            value, reason = _measurement(rows.get(note_id))
            observations.append({"take_id": take_id, "signed_cents_error": value,
                                 "absolute_cents_error": abs(value) if value is not None else None,
                                 "reliable": value is not None, "exclusion_reason": reason})
        available = [o["absolute_cents_error"] for o in observations if o["reliable"]]
        above = sum(value > threshold_cents for value in available)
        first, last = observations[0]["absolute_cents_error"], observations[-1]["absolute_cents_error"]
        improvement = first - last if len(takes) > 1 and first is not None and last is not None else None
        notes.append({"note_id": note_id, **score[note_id], "takes": observations,
                      "reliable_take_count": len(available), "above_threshold_count": above,
                      "mean_absolute_cents_error": _mean(available),
                      "first_to_last_improvement_cents": improvement,
                      "percentage_reduction": 100 * improvement / first if improvement is not None and first > 0 else None,
                      "persistence": "persistent" if above >= 2 else "insufficient_data" if len(available) < 2 else "not_persistent"})
    summaries = []
    for i, (take_id, _) in enumerate(takes):
        values = [n["takes"][i]["signed_cents_error"] for n in notes if n["takes"][i]["reliable"]]
        summaries.append({"take_id": take_id, "reliable_notes": len(values), "total_notes": len(notes),
                          "excluded_notes": len(notes) - len(values),
                          "mean_signed_cents_error": _mean(values),
                          "mean_absolute_cents_error": _mean([abs(v) for v in values])})
    paired = [n for n in notes if len(takes) > 1 and n["takes"][0]["reliable"] and n["takes"][-1]["reliable"]]
    first_mean = _mean([n["takes"][0]["absolute_cents_error"] for n in paired])
    last_mean = _mean([n["takes"][-1]["absolute_cents_error"] for n in paired])
    change = first_mean - last_mean if paired else None
    improvement = {"paired_note_count": len(paired), "first_mean_absolute_cents_error": first_mean,
                   "last_mean_absolute_cents_error": last_mean, "improvement_cents": change,
                   "percentage_reduction": 100 * change / first_mean if paired and first_mean > 0 else None}
    measures = []
    for measure in sorted({n["measure"] for n in notes}):
        subset = [n for n in notes if n["measure"] == measure]
        stats = []
        for i, (take_id, _) in enumerate(takes):
            values = [n["takes"][i]["signed_cents_error"] for n in subset if n["takes"][i]["reliable"]]
            stats.append({"take_id": take_id, "reliable_notes": len(values), "total_notes": len(subset),
                          "mean_signed_cents_error": _mean(values),
                          "mean_absolute_cents_error": _mean([abs(v) for v in values]),
                          "max_absolute_cents_error": max(map(abs, values)) if values else None,
                          "above_threshold_count": sum(abs(v) > threshold_cents for v in values)})
        measures.append({"measure": measure, "takes": stats,
                         "persistent_note_ids": [n["note_id"] for n in subset if n["persistence"] == "persistent"]})
    persistent = [n for n in notes if n["persistence"] == "persistent"]
    candidates = [n for n in notes if n["above_threshold_count"]]
    # Current issues first within persistence groups; ties use mean error and ID.
    candidates.sort(key=lambda n: (n["persistence"] != "persistent",
                                   n["takes"][-1]["absolute_cents_error"] is None,
                                   -(n["takes"][-1]["absolute_cents_error"]
                                     if n["takes"][-1]["reliable"] else n["mean_absolute_cents_error"]),
                                   -n["mean_absolute_cents_error"], n["note_id"]))
    priorities = [{"rank": i + 1, "note_id": n["note_id"], "measure": n["measure"], "pitch": n["pitch"],
                   "reason": n["persistence"] if n["persistence"] == "persistent" else "observed_above_threshold",
                   "reliable_take_count": n["reliable_take_count"], "above_threshold_count": n["above_threshold_count"],
                   "latest_signed_cents_error": n["takes"][-1]["signed_cents_error"],
                   "latest_absolute_cents_error": n["takes"][-1]["absolute_cents_error"],
                   "mean_absolute_cents_error": n["mean_absolute_cents_error"],
                   "first_to_last_improvement_cents": n["first_to_last_improvement_cents"]}
                  for i, n in enumerate(candidates)]
    return {"schema_version": 1, "threshold_cents": float(threshold_cents), "takes": summaries,
            "improvement": improvement, "notes": notes, "measures": measures,
            "persistent_errors": persistent, "practice_priorities": priorities}


def get_performance_summary(results, threshold_cents=THRESHOLD_CENTS):
    """Return take means, coverage, and paired first-to-last improvement."""
    comparison = compare_takes(results, threshold_cents)
    return {key: comparison[key] for key in ("schema_version", "threshold_cents", "takes", "improvement")}


def get_measure_analysis(results, measure=None, threshold_cents=THRESHOLD_CENTS):
    """Return all measure summaries, or a list filtered by measure number."""
    rows = compare_takes(results, threshold_cents)["measures"]
    return rows if measure is None else [row for row in rows if row["measure"] == measure]


def get_persistent_errors(results, threshold_cents=THRESHOLD_CENTS):
    """Return notes exceeding the threshold in at least two reliable takes."""
    return compare_takes(results, threshold_cents)["persistent_errors"]


def get_practice_priorities(results, threshold_cents=THRESHOLD_CENTS):
    """Return deterministic ranked observations, without generated AI advice."""
    return compare_takes(results, threshold_cents)["practice_priorities"]
