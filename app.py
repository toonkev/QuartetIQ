"""QuartetIQ rehearsal dashboard. Run: streamlit run app.py."""
import json
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from quartetiq.coach_ui import render_coach
from quartetiq.comparison import compare_takes
from quartetiq.dashboard import analyze_upload, dataset_key, load_demo

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="QuartetIQ rehearsal", page_icon="🎻", layout="wide")


@st.cache_data(show_spinner=False, max_entries=9, ttl=3600)
def cached_analysis(score: bytes, recording: bytes):
    return analyze_upload(score, recording)


@st.cache_data(show_spinner=False)
def bundled_demo():
    return load_demo(ROOT / "demo")


def cents(value):
    return "Unavailable" if value is None else f"{value:.1f} cents"


st.title("QuartetIQ rehearsal")
st.write("Compare three performances of the same solo-violin passage and find what to practise next.")
source = st.radio("Recordings", ["Try the demo", "Upload my recordings"], horizontal=True)
if source == "Try the demo":
    try:
        manifest, results = bundled_demo()
    except (OSError, ValueError) as exc:
        st.error(f"The bundled demo could not be loaded: {exc}")
        st.stop()
    st.info("Synthetic Ode to Joy demo · real measured pitch and automatic alignment. "
            "The recordings include a recurring sharp note, an improving note, and an accurate passage.")
    with st.expander("Listen to the three takes"):
        for i, take in enumerate(manifest["takes"], 1):
            st.write(f"Take {i}")
            st.audio(str(ROOT / "demo" / take["audio"]))
        st.download_button("Download demo score", (ROOT / "demo" / manifest["score"]).read_bytes(),
                           "ode_to_joy.musicxml", mime="application/vnd.recordare.musicxml+xml")
else:
    st.write("Upload one MusicXML score and three WAV recordings, earliest first. "
             "Use a complete monophonic passage: up to 120 notes and 60 seconds per recording.")
    score = st.file_uploader("MusicXML score", type=["musicxml", "xml"])
    uploads = [col.file_uploader(f"Take {i + 1}" + (" (earliest)" if i == 0 else " (latest)" if i == 2 else ""),
                                 type=["wav"], key=f"wav_{i}")
               for i, col in enumerate(st.columns(3))]
    ready = score is not None and all(upload is not None for upload in uploads)
    signature = dataset_key(score.getvalue(), [u.getvalue() for u in uploads]) if ready else None
    if st.button("Analyze recordings", type="primary", disabled=not ready):
        st.session_state.pop("uploaded_results", None)
        measured = []
        progress = st.progress(0, text="Preparing audio analysis…")
        try:
            for i, upload in enumerate(uploads):
                progress.progress(i / 3, text=f"Analyzing take {i + 1} of 3. This may take a few minutes…")
                result = cached_analysis(score.getvalue(), upload.getvalue())
                result["take_id"] = f"take_{i + 1}"
                measured.append(result)
            st.session_state.uploaded_results = (signature, measured)
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("Analysis could not finish. Check that the score contains one monophonic part and "
                     "each file is a readable mono/stereo WAV under 20 MB and 60 seconds. "
                     "Use the same complete passage in all three recordings.")
        finally:
            progress.empty()
    stored = st.session_state.get("uploaded_results")
    if not ready or stored is None or stored[0] != signature:
        st.session_state.pop("coach_conversation", None)
        st.session_state.pop("coach_dataset", None)
        st.session_state.pop("coach_tools", None)
        st.info("Choose all four files, then select Analyze recordings. Results update only after analysis.")
        st.stop()
    results = stored[1]
    st.caption("Uploaded audio is processed on the app server. Temporary files are deleted after analysis; "
               "cached analyses stay in server memory for up to one hour.")

dashboard_tab, coach_tab = st.tabs(["Rehearsal dashboard", "AI Coach"])
with dashboard_tab:
    comparison = compare_takes(results)
    st.caption("Positive cents = sharp; negative cents = flat. The 15-cent practice threshold is provisional.")
    for col, take in zip(st.columns(3), comparison["takes"]):
        col.metric(take["take_id"].replace("_", " ").title() + " · mean absolute error",
                   cents(take["mean_absolute_cents_error"]))
        col.caption(f"{take['reliable_notes']} of {take['total_notes']} notes measured reliably")
        if take["excluded_notes"]:
            st.warning(f"{take['take_id'].replace('_', ' ').title()}: {take['excluded_notes']} notes have "
                       "missing pitch or uncertain/failed alignment. These notes are excluded, not treated as in tune.")
    change = comparison["improvement"]
    if change["improvement_cents"] is None:
        st.warning("First-to-last improvement is unavailable: no reliable notes are shared by both takes.")
    else:
        reduction = change["percentage_reduction"]
        st.write(f"**First-to-last change:** {change['improvement_cents']:+.1f} cents improvement "
                 f"across {change['paired_note_count']} shared notes. "
                 + (f"Mean absolute error reduction: {reduction:+.1f}%." if reduction is not None
                    else "Percentage reduction is undefined when the first error is zero."))
    st.caption("Positive improvement means less error. Change uses only notes reliable in both the first and last takes; "
               "take averages may cover different notes.")

    st.subheader("Intonation across the passage")
    fig = go.Figure()
    for i, take in enumerate(comparison["takes"]):
        fig.add_trace(go.Scatter(x=[n["note_id"] for n in comparison["notes"]],
                                y=[n["takes"][i]["signed_cents_error"] for n in comparison["notes"]],
                                customdata=[f"Measure {n['measure']} · {n['pitch']}" for n in comparison["notes"]],
                                hovertemplate="%{customdata}<br>%{y:.1f} cents<extra>%{fullData.name}</extra>",
                                name=take["take_id"].replace("_", " ").title(), mode="lines+markers", connectgaps=False))
    fig.add_hline(y=15, line_dash="dash", line_color="gray")
    fig.add_hline(y=-15, line_dash="dash", line_color="gray")
    fig.add_hline(y=0, line_color="lightgray")
    fig.update_layout(xaxis_title="Score note (in passage order)", yaxis_title="Signed error (cents)",
                      margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")

    st.subheader("Practice priorities")
    st.write("A recurring problem exceeds 15 cents in at least two reliable takes. "
             "Priorities list recurring problems first, then larger errors in the latest take. "
             "Earlier problems that improved remain visible.")
    st.metric("Recurring problem notes (across all takes)", len(comparison["persistent_errors"]))
    if comparison["practice_priorities"]:
        st.dataframe([{"Priority": p["rank"], "Measure": p["measure"], "Pitch": p["pitch"], "Note": p["note_id"],
                       "Pattern": ("Recurring; latest within threshold" if p["reason"] == "persistent"
                                   and p["latest_absolute_cents_error"] is not None and p["latest_absolute_cents_error"] <= 15
                                   else "Recurring" if p["reason"] == "persistent" else "Observed once"),
                       "Takes over threshold": p["above_threshold_count"], "Reliable takes": p["reliable_take_count"],
                       "Latest cents": p["latest_signed_cents_error"],
                       "Improvement (cents)": p["first_to_last_improvement_cents"]}
                      for p in comparison["practice_priorities"]], hide_index=True, width="stretch")
    else:
        st.info("No reliable measurements exceed the practice threshold. Check measurement coverage before drawing conclusions.")

    st.subheader("Note-by-note measurements")
    st.caption("Blank cells are unavailable. Repeated pitches have separate score note IDs.")
    rows = []
    for n in comparison["notes"]:
        row = {"Note": n["note_id"], "Measure": n["measure"], "Pitch": n["pitch"]}
        for i, obs in enumerate(n["takes"], 1):
            row[f"Take {i} cents"] = obs["signed_cents_error"]
            row[f"Take {i} status"] = "Measured" if obs["reliable"] else obs["exclusion_reason"]
        row["Improvement (cents)"] = n["first_to_last_improvement_cents"]
        rows.append(row)
    st.dataframe(rows, hide_index=True, width="stretch")
    with st.expander("Measure-level results"):
        st.dataframe([{"Measure": m["measure"], "Take": t["take_id"], "Mean absolute cents": t["mean_absolute_cents_error"],
                       "Mean signed cents": t["mean_signed_cents_error"], "Reliable notes": t["reliable_notes"],
                       "Total notes": t["total_notes"]} for m in comparison["measures"] for t in m["takes"]],
                     hide_index=True, width="stretch")
    st.download_button("Download measured comparison", json.dumps(comparison, indent=2, allow_nan=False),
                       "quartetiq-comparison.json", mime="application/json")
    st.caption("Solo violin only. Automatic alignment is provisional, especially for slurred repeated pitches or noisy recordings. "
               "These numerical results come from measured audio and deterministic calculations.")

with coach_tab:
    render_coach(results, "synthetic demo" if source == "Try the demo" else "uploaded recordings:" + signature)
