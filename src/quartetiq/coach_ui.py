"""Session-local Streamlit interface for real Muse Spark coaching."""
import streamlit as st

from quartetiq.muse import (CoachError, answer_question, create_client, dataset_fingerprint,
                            get_api_key, test_connectivity)

QUESTIONS = ["Which measures should I practice next?", "Did my intonation improve across takes?",
             "Which notes are consistently sharp?", "What is my biggest recurring mistake?",
             "How should I practice the worst passage?"]


def render_coach(results, source):
    fingerprint = dataset_fingerprint(results, source)
    if st.session_state.get("coach_dataset") != fingerprint:
        st.session_state.coach_dataset = fingerprint
        st.session_state.pop("coach_conversation", None)
        st.session_state.pop("coach_tools", None)
    st.subheader("AI Coach · Meta Muse Spark 1.3")
    st.caption("Questions and requested measured summaries are sent to Meta. Audio is not sent. "
               "Coaching is AI-generated; verify advice against the measurements.")
    configured = bool(get_api_key(st.secrets))
    if not configured:
        st.info("Muse Spark requires MODEL_API_KEY in the environment or Streamlit secrets. "
                "The numerical dashboard and deterministic practice priorities remain available; they are not AI responses.")
    if st.button("Test Meta connection", disabled=not configured):
        try:
            with create_client(st.secrets) as client:
                test_connectivity(client)
            st.success("Authenticated Meta request succeeded. This connection check does not test tool calling.")
        except CoachError as exc:
            st.error(str(exc))
    if st.button("Clear coaching conversation"):
        st.session_state.pop("coach_conversation", None)
        st.session_state.pop("coach_tools", None)
    conversation = st.session_state.get("coach_conversation")
    for turn in (conversation or {}).get("turns", []):
        # Display the musician's original question and the final grounded answer.
        with st.chat_message("user"):
            st.markdown(turn[0]["content"])
        with st.chat_message("assistant"):
            st.markdown(turn[-1]["content"])
    suggested = st.selectbox("Suggested questions", QUESTIONS)
    send_suggested = st.button("Ask suggested question", disabled=not configured)
    question = st.chat_input("Ask about this passage", disabled=not configured, max_chars=4000)
    if send_suggested:
        question = suggested
    if question:
        try:
            with st.spinner("Muse Spark is reviewing your measured results…"):
                with create_client(st.secrets) as client:
                    reply = answer_question(client, results, question, conversation, source=source)
            st.session_state.coach_conversation = reply["conversation"]
            st.session_state.coach_tools = reply["tools_used"]
            st.rerun()
        except CoachError as exc:
            st.error(str(exc))
    if st.session_state.get("coach_tools"):
        st.caption("Measurement tools used for the latest answer: " + ", ".join(st.session_state.coach_tools))
