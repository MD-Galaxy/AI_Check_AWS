# Bedrock Model Availability Checker (POC)

A small proof-of-concept that checks which AI model providers your AWS
account actually has access to on Amazon Bedrock — and proves it by sending
each one a real request, not just checking a listing.

> **Running this as part of the root project?** `src/app.py` mounts this
> POC's FastAPI routes into EmailPOC's own app, so both are served by one
> process on one port (`http://localhost:8000/check-bedrock/` by default —
> see the root [`README.md`](../README.md)). Everything below describes
> running this folder entirely on its own instead, on its own port — useful
> if you're developing just this piece, or deploying it as a separate
> service.

## What it does

1. Lists every foundation model your AWS account/region can see
   (`bedrock.list_foundation_models()`).
2. Prints the full, distinct set of AI service provider **names** available
   in the selected region (e.g. `Amazon, Anthropic, Cohere, DeepSeek, ...`)
   — every provider Bedrock exposes there, not just the five checked below.
   This also lands in the JSON report as `all_providers_in_region`.
3. Searches that list for five specific providers by `modelId` keyword:
   - **Claude** → `modelId` contains `anthropic`
   - **DeepSeek** → `modelId` contains `deepseek`
   - **Qwen** → `modelId` contains `qwen`
   - **ChatGPT** → `modelId` contains `openai` or `gpt`
   - **Zhipu GLM** → `modelId` contains `glm` or `zhipu`

   > Note: at the time this POC was originally written, ChatGPT (OpenAI) and
   > Zhipu GLM were not Bedrock partners and were expected to always show
   > `NOT AVAILABLE ON BEDROCK`. AWS's model catalog has since grown to
   > include OpenAI's open-weight models (`openai.gpt-oss-*`) and Zhipu's
   > GLM (`zai.glm-*`) in some regions — so don't be surprised if your run
   > shows them as `ACCESSIBLE`. Bedrock's partner catalog changes over
   > time; treat the script's live output as authoritative, not this doc.
4. For every provider that **is** listed, picks a best-guess "newest /
   most capable" match (see `model_matcher.pick_invoke_candidate`; Claude
   is pinned to `claude-sonnet-5` specifically since Anthropic's newest
   model on Bedrock, `claude-fable-5`, only supports inference-profile
   invocation) and actually invokes it via `bedrock-runtime`'s `converse()`
   API with the prompt `"Reply with exactly one word: OK"`, recording the
   response text and latency as live proof it works.
   - If the bare model ID fails specifically because Bedrock requires a
     cross-region **inference profile** for it, the call is automatically
     retried once through a matching profile (`bedrock.list_inference_profiles()`)
     — see `bedrock_client.invoke_model()`. The report's
     `used_inference_profile` field records whether this happened.
5. For providers that are **not** listed, skips invocation entirely and
   marks them `NOT AVAILABLE ON BEDROCK`.
6. As a final, separate check, calls Claude **directly via the Anthropic
   API** (not through AWS Bedrock at all) using `ANTHROPIC_API_KEY`, with
   the model set by `ANTHROPIC_TEST_MODEL` (default `claude-sonnet-5`).
   This answers a different question than the Bedrock checks above: "can
   we reach Claude directly with an Anthropic API key," independent of AWS
   entirely. Appears as `Manual Claude API Access` at the end of the
   summary/report. Skipped (not treated as an error) if `ANTHROPIC_API_KEY`
   isn't set.
7. Prints a console table (via `rich`) and writes a full JSON report to
   `bedrock_availability_report.json`.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` to set your region and credentials. Three ways to supply
credentials, checked in this order:

1. **Explicit keys in `.env`** — set `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY` (plus `AWS_SESSION_TOKEN` if you're using
   temporary credentials). If both are set, they're used regardless of
   anything else configured on the system.
2. **A named profile** — set `AWS_PROFILE` in `.env` to reuse a profile
   already configured in `~/.aws/credentials`. Ignored if explicit keys
   (option 1) are set.
3. **System default** — if neither of the above is set, falls back to
   boto3's own default credential chain (env vars already in your shell,
   `~/.aws/credentials`, an IAM role, SSO, etc.)

`.env` is listed in `.gitignore` and won't be committed — keep real
credentials out of version control.

Your IAM principal needs at least:
- `bedrock:ListFoundationModels`
- `bedrock:InvokeModel` (used internally by `converse()`) for whichever
  models it ends up invoking
- `bedrock:ListInferenceProfiles` (optional but recommended — without it,
  the automatic inference-profile retry described below silently can't find
  a profile and the original error is reported instead)

**Optional — direct Anthropic API check:** set `ANTHROPIC_API_KEY` in
`.env` to also enable the `Manual Claude API Access` check (calls Claude
directly via Anthropic's API, bypassing Bedrock/AWS entirely). Leave it
unset to skip this check — it shows as `NOT CONFIGURED`, not an error.

## Run it (CLI)

```bash
python main.py
```

## Run it as a web service

`app.py` wraps `main.run_check()` in a small **FastAPI** app, so it can run
as a long-lived service (e.g. behind an ALB on ECS, or alongside another
project in the same Docker stack) instead of a one-off CLI run. Every route
is served under the `/check-bedrock` base path (`BASE_PATH` in `app.py`) so
it can share a host with other services without route collisions — see the
root [`../README.md`](../README.md) for how this runs together with
EmailPOC in one `docker compose` stack.

```bash
# Local dev (hot-reload)
uvicorn app:app --host 0.0.0.0 --port 8080 --reload

# Production — via gunicorn + the Uvicorn worker class (also what the Dockerfile uses)
gunicorn --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080 --workers 2 app:app
```

| Route | Behavior |
|---|---|
| `GET /health` | Trivial `200 ok`, no Bedrock/Anthropic calls — safe for an ALB target group health check. Bare path (not under `/check-bedrock`) since that's the conventional fixed path most health-check tooling expects. |
| `GET /check-bedrock/` | Runs the full check (same `run_check()` as the CLI — Bedrock providers **and** the direct Anthropic check) and returns it as JSON. Returns `500` with a JSON `error` body (not a stack trace) if Bedrock credentials are missing/invalid entirely. |

### Docker

```bash
docker build -t bedrock-availability-poc .
docker run -p 8080:8080 --env-file .env bedrock-availability-poc
```

Then open **http://localhost:8080/check-bedrock/**.

`.dockerignore` excludes `.env` from the build context — credentials are
passed in at **run time** via `--env-file` / your orchestrator's secret
injection (e.g. ECS task definition secrets), never baked into the image.

## Project layout

| File | Purpose |
|---|---|
| `main.py` | CLI entry point + `run_check()` — the shared core logic: list → match → invoke (Bedrock) → direct Anthropic check. Used by both the CLI and `app.py`. |
| `app.py` | FastAPI web wrapper around `main.run_check()` — exposes `/check-bedrock/health` and `/check-bedrock/` |
| `Dockerfile` / `.dockerignore` | Container build for running `app.py` behind gunicorn (Uvicorn worker class) |
| `bedrock_client.py` | boto3 wrapper: `list_foundation_models()`, `invoke_model()` (Converse API, with automatic inference-profile retry), `list_inference_profiles()` |
| `model_matcher.py` | Keyword matching logic that groups models by provider, `pick_invoke_candidate()` to choose which matched model to invoke, and `list_provider_names()` for the full provider-name listing |
| `anthropic_client.py` | `invoke_claude_direct()` — calls Claude directly via the official `anthropic` SDK, independent of Bedrock/AWS |
| `config.py` | Region / credentials / prompt / other settings, loaded from env vars or `.env` |
| `requirements.txt` | `boto3`, `rich`, `python-dotenv`, `fastapi`, `uvicorn`, `gunicorn`, `anthropic` |
| `bedrock_availability_report.json` | Generated by CLI runs — full machine-readable result (the web service returns the same shape directly in the HTTP response instead) |

## Reading the summary

```
Claude                    -> ACCESSIBLE                    (responded in 0.8s: "OK")
DeepSeek                  -> ACCESSIBLE                    (responded in 1.1s: "OK")
Qwen                      -> LISTED BUT FAILED TO INVOKE   (AccessDeniedException)
ChatGPT                   -> NOT AVAILABLE ON BEDROCK
Zhipu GLM                 -> NOT AVAILABLE ON BEDROCK
Manual Claude API Access  -> ACCESSIBLE                    (responded in 0.6s: "OK")
```

| Status | Meaning |
|---|---|
| `ACCESSIBLE` | The model is listed **and** responded successfully to a real invocation. Latency and the returned text are shown as proof. If it only worked via a cross-region inference profile, `used_inference_profile` in the JSON report names the profile used. |
| `LISTED BUT FAILED TO INVOKE` | Bedrock's model catalog shows this provider, but the actual `converse()` call failed — e.g. `AccessDeniedException` (no model-access grant, or — as seen in testing — `INVALID_PAYMENT_INSTRUMENT` meaning the account has no valid payment method on file for the AWS Marketplace subscription this model requires), `ResourceNotFoundException` (a legacy model needs reactivation), `ValidationException` (a required inference profile wasn't found, or another request-shape issue), `ThrottlingException`, or similar. This is a **different failure mode** than "not offered" — the account/model is one step away from working, not fundamentally unavailable. |
| `NOT AVAILABLE ON BEDROCK` | No model from this provider appears in `list_foundation_models()` at all for this account/region. |
| `FAILED TO INVOKE` | **`Manual Claude API Access` only.** `ANTHROPIC_API_KEY` is set, but the direct Anthropic API call failed — e.g. `authentication_error` (bad/revoked key), `permission_error`, `rate_limit_error`, or a network failure. |
| `NOT CONFIGURED` | **`Manual Claude API Access` only.** `ANTHROPIC_API_KEY` isn't set, so this check was skipped — not treated as a failure. |

If credentials are missing or invalid entirely (not just missing model
access), the script exits early with a clear, actionable error message
instead of a stack trace.

## Notes

- This is a proof of concept — it invokes one best-guess model per Bedrock
  provider (see `model_matcher.pick_invoke_candidate`), uses a fixed
  one-word test prompt, and keeps error handling simple. It is not meant
  for production monitoring.
- Model availability varies by AWS region — if everything shows as
  `NOT AVAILABLE ON BEDROCK`, double-check `AWS_REGION` in your `.env`.
- The `Manual Claude API Access` check is entirely independent of the
  Bedrock checks above — it uses Anthropic's own API and its own billing,
  not AWS/Bedrock. A failure there does not mean Bedrock access is broken,
  and vice versa.
