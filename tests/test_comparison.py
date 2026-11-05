"""Independent arithmetic fixtures for the read-only comparison API."""
from copy import deepcopy
import json

import pytest

from quartetiq.comparison import (compare_takes, get_performance_summary, get_measure_analysis,
                                  get_persistent_errors, get_practice_priorities)


def row(note_id, value, measure=1, **overrides):
    return {"id": note_id, "measure": measure, "pitch": "A4", "midi": 69.,
            "onset_quarters": float(ord(note_id[-1]) - ord("a")), "duration_quarters": 1.,
            "status": "ok", "alignment_status": "aligned", "cents_deviation": value, **overrides}


@pytest.fixture
def takes():
    return [{"take_id": f"take_{i + 1}", "notes": [row("a", a), row("b", b), row("c", c, measure=2)]}
            for i, (a, b, c) in enumerate([(30, -45, 0), (32, -10, 3), (31, -3, -3)])]


def test_three_takes_and_stable_ids(takes):
    takes[1]["notes"].reverse()
    result = compare_takes(takes)
    assert [n["note_id"] for n in result["notes"]] == ["a", "b", "c"]
    assert [t["mean_absolute_cents_error"] for t in result["takes"]] == pytest.approx([25, 15, 37 / 3])
    assert result["notes"][1]["takes"][0]["signed_cents_error"] == -45
    assert result["notes"][1]["takes"][0]["absolute_cents_error"] == 45
    assert result["notes"][1]["first_to_last_improvement_cents"] == 42
    assert [n["note_id"] for n in result["persistent_errors"]] == ["a"]
    assert [n["note_id"] for n in result["practice_priorities"]] == ["a", "b"]
    assert result["measures"][0]["takes"][0]["mean_signed_cents_error"] == -7.5
    assert result["measures"][0]["takes"][0]["mean_absolute_cents_error"] == 37.5


def test_improvement_uses_paired_notes(takes):
    takes[2]["notes"][0]["alignment_status"] = "uncertain"
    result = compare_takes(takes)
    change = result["improvement"]
    assert change["paired_note_count"] == 2
    assert change["first_mean_absolute_cents_error"] == 22.5
    assert change["last_mean_absolute_cents_error"] == 3
    assert change["improvement_cents"] == 19.5
    assert change["percentage_reduction"] == pytest.approx(100 * 19.5 / 22.5)
    assert result["notes"][0]["first_to_last_improvement_cents"] is None
    assert result["notes"][0]["persistence"] == "persistent"  # Two reliable occurrences, coverage explicit.
    assert result["notes"][0]["reliable_take_count"] == 2


@pytest.mark.parametrize("value,alignment,status", [(None, "aligned", "ok"), (float("nan"), "aligned", "ok"),
    (float("inf"), "aligned", "ok"), (32, "failed", "ok"), (32, "uncertain", "ok"),
    (32, None, "ok"), (32, "aligned", "insufficient_frames")])
def test_unavailable_measurements(takes, value, alignment, status):
    takes[0]["notes"][0].update(cents_deviation=value, alignment_status=alignment, status=status)
    result = compare_takes(takes)
    assert result["takes"][0]["excluded_notes"] == 1
    assert result["takes"][0]["mean_absolute_cents_error"] == 22.5
    assert result["notes"][0]["takes"][0]["absolute_cents_error"] is None
    json.dumps(result, allow_nan=False)


def test_missing_rows_and_insufficient_evidence(takes):
    takes[0]["notes"].pop(0)
    takes[1]["notes"].pop(0)
    result = compare_takes(takes)
    note = result["notes"][0]
    assert note["takes"][0]["exclusion_reason"] == "missing_note"
    assert note["persistence"] == "insufficient_data"
    assert note["mean_absolute_cents_error"] == 31
    assert result["takes"][0]["total_notes"] == 3


def test_zero_baseline_worsening_and_threshold():
    takes = [{"notes": [row("a", v)]} for v in (0, 15, 20)]
    result = compare_takes(takes)
    assert result["improvement"]["improvement_cents"] == -20
    assert result["improvement"]["percentage_reduction"] is None
    assert result["notes"][0]["above_threshold_count"] == 1
    assert not result["persistent_errors"]
    takes[0]["notes"][0]["cents_deviation"] = 10
    assert compare_takes(takes)["improvement"]["percentage_reduction"] == -100


def test_no_reliable_data_or_single_take():
    takes = [{"notes": [row("a", None)]} for _ in range(3)]
    result = compare_takes(takes)
    assert all(t["mean_absolute_cents_error"] is None for t in result["takes"])
    assert result["improvement"]["improvement_cents"] is None
    assert not result["practice_priorities"]
    assert compare_takes([{"notes": [row("a", 20)]}])["improvement"]["improvement_cents"] is None


@pytest.mark.parametrize("function", [get_performance_summary, compare_takes, get_measure_analysis,
                                       get_persistent_errors, get_practice_priorities])
def test_json_tools_are_read_only(takes, function):
    original = deepcopy(takes)
    output = function(takes)
    assert json.loads(json.dumps(output, allow_nan=False)) == output
    assert takes == original


def test_measure_filter(takes):
    assert [m["measure"] for m in get_measure_analysis(takes, 2)] == [2]
    assert get_measure_analysis(takes, 999) == []


@pytest.mark.parametrize("mutation", ["duplicate_note", "duplicate_take", "different_score", "no_notes"])
def test_invalid_inputs(takes, mutation):
    if mutation == "duplicate_note":
        takes[0]["notes"].append(takes[0]["notes"][0])
    elif mutation == "duplicate_take":
        takes[1]["take_id"] = "take_1"
    elif mutation == "different_score":
        takes[1]["notes"][0]["midi"] = 70
    else:
        del takes[0]["notes"]
    with pytest.raises(ValueError):
        compare_takes(takes)
    with pytest.raises(ValueError):
        compare_takes([])


def test_constant_tempo_is_explicitly_supported(takes):
    takes[0]["notes"][0]["alignment_status"] = "constant_tempo"
    assert compare_takes(takes)["takes"][0]["reliable_notes"] == 3
