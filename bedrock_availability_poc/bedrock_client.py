"""
Thin boto3 wrapper around the Bedrock APIs this POC needs:

- bedrock.list_foundation_models()      -> discover what the account can see
- bedrock.list_inference_profiles()     -> discover cross-region profiles
- bedrock-runtime.converse()            -> actually invoke a model

converse() is used instead of the provider-specific invoke_model() body
formats because it presents a single, provider-agnostic request/response
shape that Bedrock translates for every supported model family (Anthropic,
DeepSeek, Qwen, Meta, etc.), which keeps this POC simple.

Many current-generation models are not invokable by bare model ID at all —
Bedrock requires routing them through a "cross-region inference profile"
instead (AWS's load-balancing mechanism for high-demand models). invoke_model()
detects that specific failure and automatically retries once via a matching
inference profile, if one exists.
"""

import time

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

import config


class BedrockAuthError(Exception):
    """Raised when AWS credentials or permissions are missing/invalid."""


# Cache of inference profile summaries for this process, populated on first
# use. Avoids re-listing profiles for every provider in a single run.
_inference_profiles_cache = None


def _session():
    kwargs = {"region_name": config.AWS_REGION}
    if config.AWS_PROFILE:
        kwargs["profile_name"] = config.AWS_PROFILE
    return boto3.Session(**kwargs)


def get_bedrock_client():
    """Control-plane client: model discovery, metadata."""
    return _session().client("bedrock")


def get_bedrock_runtime_client():
    """Data-plane client: actually running inference."""
    return _session().client("bedrock-runtime")


def list_foundation_models():
    """
    Fetch every foundation model the account/region can see.

    Returns the raw list of model summary dicts from the API.
    Raises BedrockAuthError on missing/invalid credentials or permissions.
    """
    client = get_bedrock_client()
    try:
        response = client.list_foundation_models()
    except NoCredentialsError as exc:
        raise BedrockAuthError(
            "No AWS credentials found. Configure them via `aws configure`, "
            "environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY), "
            "or an IAM role, then retry."
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("UnrecognizedClientException", "AccessDeniedException"):
            raise BedrockAuthError(
                f"AWS rejected the request ({code}). Verify your credentials "
                "are valid and the IAM principal has bedrock:ListFoundationModels "
                f"permission in region '{config.AWS_REGION}'."
            ) from exc
        raise

    return response.get("modelSummaries", [])


def list_inference_profiles():
    """
    Fetch every inference profile visible in this account/region, handling
    pagination. Returns [] (rather than raising) if the call fails — this is
    a best-effort fallback lookup, not a required capability of the POC.
    """
    global _inference_profiles_cache
    if _inference_profiles_cache is not None:
        return _inference_profiles_cache

    client = get_bedrock_client()
    profiles = []
    next_token = None
    try:
        while True:
            kwargs = {"nextToken": next_token} if next_token else {}
            response = client.list_inference_profiles(**kwargs)
            profiles.extend(response.get("inferenceProfileSummaries", []))
            next_token = response.get("nextToken")
            if not next_token:
                break
    except (ClientError, NoCredentialsError):
        # Missing bedrock:ListInferenceProfiles permission, or the feature
        # isn't available here — treat as "no profiles found" rather than
        # failing the whole run.
        profiles = []

    _inference_profiles_cache = profiles
    return profiles


def find_inference_profile_id(model_id):
    """
    Find a system-defined inference profile whose underlying models include
    model_id. Profile "models" entries carry ARNs like
    'arn:aws:bedrock:<region>::foundation-model/<model_id>', so a profile
    matches if any of its model ARNs end with our model_id.

    Returns the profile's inferenceProfileId, or None if no match is found.
    """
    for profile in list_inference_profiles():
        model_arns = (m.get("modelArn", "") for m in profile.get("models", []))
        if any(arn.endswith(model_id) for arn in model_arns):
            return profile.get("inferenceProfileId")
    return None


def _requires_inference_profile(error_code, error_message):
    return error_code == "ValidationException" and "inference profile" in (
        error_message or ""
    ).lower()


def _converse_once(client, model_id, prompt, max_tokens):
    """
    Single, non-retrying Converse API call. Returns the same result dict
    shape as invoke_model(); raises BedrockAuthError on missing credentials.
    """
    start = time.perf_counter()
    try:
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            # No "temperature" here on purpose: newer models (e.g. current
            # Claude releases) reject an explicit sampling temperature
            # outright, and omitting it is harmless for every other
            # provider — Bedrock just uses each model's own default.
            inferenceConfig={"maxTokens": max_tokens},
        )
    except NoCredentialsError as exc:
        raise BedrockAuthError(
            "No AWS credentials found while invoking Bedrock. Configure them "
            "via `aws configure`, environment variables, or an IAM role."
        ) from exc
    except ClientError as exc:
        latency = time.perf_counter() - start
        error_info = exc.response.get("Error", {})
        return {
            "ok": False,
            "latency_seconds": round(latency, 3),
            "text": None,
            "error": error_info.get("Code", exc.__class__.__name__),
            "error_message": error_info.get("Message", str(exc)),
        }
    except Exception as exc:  # noqa: BLE001 - record any other invocation failure
        latency = time.perf_counter() - start
        return {
            "ok": False,
            "latency_seconds": round(latency, 3),
            "text": None,
            "error": exc.__class__.__name__,
            "error_message": str(exc),
        }

    latency = time.perf_counter() - start
    text = ""
    try:
        content_blocks = response["output"]["message"]["content"]
        text = "".join(block.get("text", "") for block in content_blocks).strip()
    except (KeyError, IndexError, TypeError):
        text = ""

    return {
        "ok": True,
        "latency_seconds": round(latency, 3),
        "text": text,
        "error": None,
        "error_message": None,
    }


def invoke_model(model_id, prompt=None, max_tokens=None):
    """
    Invoke a single Bedrock model via the Converse API with a simple prompt.

    If the bare model_id fails specifically because Bedrock requires an
    inference profile for it, this automatically looks one up via
    find_inference_profile_id() and retries once through the profile.

    Returns a dict:
        {
            "ok": bool,
            "latency_seconds": float,
            "text": str | None,
            "error": str | None,                # exception class / Bedrock error code
            "error_message": str | None,
            "used_inference_profile": str | None,  # profile id, if a retry was used
        }

    Does not raise for invocation failures (throttling, access denied, model
    not ready, region mismatch, etc.) — those are recorded in the result so
    the caller can distinguish "listed but failed to invoke" from success.
    Auth errors (no credentials at all) still raise BedrockAuthError since
    that is a setup problem, not a per-model problem.
    """
    prompt = prompt or config.TEST_PROMPT
    max_tokens = max_tokens or config.TEST_MAX_TOKENS

    client = get_bedrock_runtime_client()
    result = _converse_once(client, model_id, prompt, max_tokens)

    if not result["ok"] and _requires_inference_profile(
        result["error"], result["error_message"]
    ):
        profile_id = find_inference_profile_id(model_id)
        if profile_id:
            retry_result = _converse_once(client, profile_id, prompt, max_tokens)
            retry_result["used_inference_profile"] = profile_id
            return retry_result

    result["used_inference_profile"] = None
    return result
