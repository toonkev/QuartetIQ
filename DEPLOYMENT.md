# Streamlit Community Cloud

The app is ready to deploy; no cloud deployment or public URL is claimed by this
repository. Local demo loading does not need credentials or model services.

1. Push this repository to a GitHub repository accessible to your Streamlit
   Community Cloud account. Include `app.py`, `pyproject.toml`, `uv.lock`,
   `requirements.txt`, `src/`, `.streamlit/config.toml`, and the entire `demo/`
   directory. The roughly 3.5 MB demo needs no Git LFS or external downloads.
2. In [Streamlit Community Cloud](https://share.streamlit.io/), choose **Create
   app**, select the repository and branch, and use `app.py` as the entrypoint
   (or its repository-relative path if the project is in a subdirectory).
3. Under advanced settings, select **Python 3.12**. The verified numerical stack
   requires Python >=3.12,<3.13. Do not accept a different default interpreter.
4. Deploy. Community Cloud can resolve the uv project from `uv.lock`; the provided
   `requirements.txt` is also a pinned pip-compatible export and installs the
   local `quartetiq` package via `.`. Keep these files consistent. No secrets or
   external system packages are required for the numerical WAV demo. The AI Coach
   requires the Meta secret described below.
5. Verify that three take metrics, the Plotly chart, note table, priorities, and
   audio players load without clicking Analyze. Test the JSON download.
6. Select upload mode and test the bundled score/WAVs as uploads. Confirm the
   results match the bundled demo. Then test a silent recording: it must show
   missing/failed-alignment warnings and unavailable measurements.

Uploaded pYIN processing can take minutes on a small shared CPU, particularly
on the first request. Limits are 60 seconds per WAV, 20 MB, two channels, and
120 score notes. The app caches up to nine analyses for one hour; reruns reuse
unchanged files. Server restarts clear the in-memory cache. The bundled demo
always loads precomputed **real measured** results without running pYIN.

Uploads are processed on the hosting server. Temporary files are deleted;
Streamlit retains upload/session data in memory, and cached analysis outputs
are shared within the app server process. This milestone does not provide user
accounts, persistent storage, job queues, or a multi-user security boundary.
Do not add secrets to the repository. Muse Spark coaching sends questions and requested measured summaries to Meta;
raw audio is not sent. Configure its credentials through the hosting service's
secrets as described below.

## Local startup

```bash
uv sync --frozen
uv run streamlit run app.py
```

Open the localhost URL printed by Streamlit. For a pip-only environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

## Dependency updates

Keep the NumPy 2.2 / Numba 0.61 / SciPy 1.15 compatibility constraints unless a
separate numerical validation warrants changing them. After changing declared
dependencies:

```bash
uv lock
uv sync --frozen
uv export --frozen --no-dev --no-hashes --no-emit-project --output-file requirements.txt
printf '\n.\n' >> requirements.txt
uv run pytest
```

If deployment reports an import error for `quartetiq`, confirm that the project
package was installed and the app root contains the local-package `.` entry in
`requirements.txt`. If startup fails in pYIN, check the interpreter and installed
numerical versions against `uv.lock` before changing analysis code.

## Configure Meta Muse Spark

In Community Cloud, open the app settings and its **Secrets** editor. Add the
following TOML entry, replacing the placeholder with your actual Meta key:

```toml
MODEL_API_KEY = "YOUR_META_MODEL_API_KEY"
```

Save and restart/reboot the app if needed so the running process sees the secret.
For local Streamlit runs, put the same entry in `.streamlit/secrets.toml`; this
file and `.env` files are gitignored. Alternatively set `MODEL_API_KEY` securely
in the server environment. The app does not automatically load `.env` files.
Never paste credentials into chat, commit them, or put them in a URL. The OpenAI
SDK receives the Meta key explicitly; `OPENAI_API_KEY` is not used.

Open **AI Coach** and click **Test Meta connection**. A successful check means
an authenticated Chat Completion worked, not that function calling was tested.
Then ask “Which measures should I practice next?” Verify that the UI lists the
measurement tools used and that the answer agrees with the demo's measured
results. Test a follow-up and switch datasets to confirm the history resets.

The endpoint and model are fixed to `https://api.meta.ai/v1` and
`muse-spark-1.3`. Hosting must allow outbound HTTPS to `api.meta.ai`, and the Meta
account/key must have access and quota for this model. Requests have a 45-second
timeout and one SDK retry; the orchestration loop is separately bounded. Quota,
authentication, timeouts, and connection errors are reported without provider
exception bodies or credentials. No fallback response is labelled as Muse Spark.

No key is needed to run the mocked test suite. Live verification requires a real
configured credential; see the CLI smoke tests in README and the actual results
in VERIFICATION.md. Community Cloud deployment itself is still a separate step.
