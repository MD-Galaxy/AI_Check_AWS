# Bedrock Model Availability Checker (POC)

A small proof-of-concept that checks which AI model providers your AWS
account actually has access to on Amazon Bedrock — and proves it by sending
each one a real request, not just checking a listing.

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
6. Prints a console table (via `rich`) and writes a full JSON report to
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

## Run it

```bash
python main.py
```

## Project layout

| File | Purpose |
|---|---|
| `main.py` | Entry point — orchestrates list → match → invoke → report |
| `bedrock_client.py` | boto3 wrapper: `list_foundation_models()`, `invoke_model()` (Converse API, with automatic inference-profile retry), `list_inference_profiles()` |
| `model_matcher.py` | Keyword matching logic that groups models by provider, `pick_invoke_candidate()` to choose which matched model to invoke, and `list_provider_names()` for the full provider-name listing |
| `config.py` | Region / prompt / other settings, loaded from env vars or `.env` |
| `requirements.txt` | `boto3`, `rich`, `python-dotenv` |
| `bedrock_availability_report.json` | Generated on each run — full machine-readable result |

## Reading the summary

```
Claude       -> ACCESSIBLE                    (responded in 0.8s: "OK")
DeepSeek     -> ACCESSIBLE                    (responded in 1.1s: "OK")
Qwen         -> LISTED BUT FAILED TO INVOKE   (AccessDeniedException)
ChatGPT      -> NOT AVAILABLE ON BEDROCK
Zhipu GLM    -> NOT AVAILABLE ON BEDROCK
```

| Status | Meaning |
|---|---|
| `ACCESSIBLE` | The model is listed **and** responded successfully to a real invocation. Latency and the returned text are shown as proof. If it only worked via a cross-region inference profile, `used_inference_profile` in the JSON report names the profile used. |
| `LISTED BUT FAILED TO INVOKE` | Bedrock's model catalog shows this provider, but the actual `converse()` call failed — e.g. `AccessDeniedException` (no model-access grant, or — as seen in testing — `INVALID_PAYMENT_INSTRUMENT` meaning the account has no valid payment method on file for the AWS Marketplace subscription this model requires), `ResourceNotFoundException` (a legacy model needs reactivation), `ValidationException` (a required inference profile wasn't found, or another request-shape issue), `ThrottlingException`, or similar. This is a **different failure mode** than "not offered" — the account/model is one step away from working, not fundamentally unavailable. |
| `NOT AVAILABLE ON BEDROCK` | No model from this provider appears in `list_foundation_models()` at all for this account/region. |

If credentials are missing or invalid entirely (not just missing model
access), the script exits early with a clear, actionable error message
instead of a stack trace.

## Notes

- This is a proof of concept — it invokes only the **first** matching model
  per provider, uses a fixed one-word test prompt, and keeps error handling
  simple. It is not meant for production monitoring.
- Model availability varies by AWS region — if everything shows as
  `NOT AVAILABLE ON BEDROCK`, double-check `AWS_REGION` in your `.env`.
