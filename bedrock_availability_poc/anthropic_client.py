"""
Direct Anthropic API check — calls Claude via Anthropic's own API (the
official `anthropic` SDK), completely independent of AWS Bedrock. This is
a separate proof of access: it answers "can we reach Claude directly with
an Anthropic API key" as opposed to "can we reach Claude via Bedrock."
"""

import time

import anthropic

import config


def invoke_claude_direct(prompt=None, max_tokens=None):
    """
    Invoke Claude directly via the Anthropic API using ANTHROPIC_API_KEY.

    Returns a dict:
        {
            "configured": bool,             # False if ANTHROPIC_API_KEY isn't set
            "ok": bool,
            "latency_seconds": float | None,
            "text": str | None,
            "error": str | None,
            "error_message": str | None,
        }

    Never raises — a missing key or any API failure is recorded in the
    result rather than propagated, since this check is independent of (and
    optional alongside) the Bedrock-based ones.
    """
    if not config.ANTHROPIC_API_KEY:
        return {
            "configured": False,
            "ok": False,
            "latency_seconds": None,
            "text": None,
            "error": "NotConfigured",
            "error_message": "ANTHROPIC_API_KEY is not set - skipped.",
        }

    prompt = prompt or config.TEST_PROMPT
    max_tokens = max_tokens or config.TEST_MAX_TOKENS

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    start = time.perf_counter()
    try:
        response = client.messages.create(
            model=config.ANTHROPIC_TEST_MODEL,
            max_tokens=max_tokens,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as exc:
        latency = time.perf_counter() - start
        # exc.message is the full "Error code: 401 - {...}" dump; the inner
        # body carries the clean human-readable reason on its own.
        clean_message = (exc.body or {}).get("error", {}).get("message") if isinstance(exc.body, dict) else None
        return {
            "configured": True,
            "ok": False,
            "latency_seconds": round(latency, 3),
            "text": None,
            "error": exc.type or exc.__class__.__name__,
            "error_message": clean_message or getattr(exc, "message", str(exc)),
        }
    except anthropic.APIConnectionError as exc:
        latency = time.perf_counter() - start
        return {
            "configured": True,
            "ok": False,
            "latency_seconds": round(latency, 3),
            "text": None,
            "error": exc.__class__.__name__,
            "error_message": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 - record any other invocation failure
        latency = time.perf_counter() - start
        return {
            "configured": True,
            "ok": False,
            "latency_seconds": round(latency, 3),
            "text": None,
            "error": exc.__class__.__name__,
            "error_message": str(exc),
        }

    latency = time.perf_counter() - start
    text = next((b.text for b in response.content if b.type == "text"), "").strip()

    return {
        "configured": True,
        "ok": True,
        "latency_seconds": round(latency, 3),
        "text": text,
        "error": None,
        "error_message": None,
    }
