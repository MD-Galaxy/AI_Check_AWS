"""
Keyword matching logic for finding provider models within a Bedrock
list_foundation_models() response.
"""

import re

# Each provider maps to a list of substrings checked (case-insensitively)
# against a model's modelId. A model matches a provider if ANY keyword hits.
PROVIDER_KEYWORDS = {
    "Claude": ["anthropic"],
    "DeepSeek": ["deepseek"],
    "Qwen": ["qwen"],
    "ChatGPT": ["openai", "gpt"],
    "Zhipu GLM": ["glm", "zhipu"],
}

_DATE_RE = re.compile(r"\d{8}")  # e.g. the 20240307 in claude-3-haiku-20240307
_NUM_RE = re.compile(r"\d+")

# Per-provider override: if a matched model id contains this substring,
# invoke that one instead of running the newness heuristic below. Useful
# when the "newest" model needs special deployment (e.g. claude-fable-5 on
# Bedrock only supports invocation via an inference profile, not on-demand)
# and a specific, reliably invokable model is preferred instead.
PREFERRED_MODEL_SUBSTRING = {
    "Claude": "claude-sonnet-5",
}


def _newness_key(model_id):
    """
    Best-effort "how new/capable is this" sort key for a Bedrock modelId.

    This is NOT a real semantic-version parser — every provider names models
    differently, so it's approximate. Heuristic: an embedded 8-digit date
    (e.g. "...-20240307-v1:0") usually marks an older, dated legacy snapshot,
    so undated IDs are preferred first. Among IDs with the same "datedness",
    higher embedded version numbers win (e.g. opus-4-8 over opus-4-6).
    """
    is_dated = bool(_DATE_RE.search(model_id))
    numbers = tuple(int(n) for n in _NUM_RE.findall(model_id))
    return (not is_dated, numbers)


def pick_invoke_candidate(provider, model_summaries):
    """
    Pick the single model to invoke out of a provider's matched model
    summaries: the provider's PREFERRED_MODEL_SUBSTRING match if one exists,
    otherwise the best-guess newest/most-capable model. Best-effort only —
    see _newness_key.
    """
    model_ids = [m.get("modelId") for m in model_summaries]

    preferred = PREFERRED_MODEL_SUBSTRING.get(provider)
    if preferred:
        preferred_matches = [m for m in model_ids if preferred in m]
        if preferred_matches:
            return max(preferred_matches, key=_newness_key)

    return max(model_ids, key=_newness_key)


def match_providers(model_summaries, keywords=None):
    """
    Group Bedrock model summaries by provider keyword match.

    Args:
        model_summaries: list of dicts as returned by
            bedrock.list_foundation_models()["modelSummaries"]
        keywords: optional override of PROVIDER_KEYWORDS

    Returns:
        dict mapping provider name -> list of matching model summaries,
        sorted by modelId for determinism. Providers with no matches map
        to an empty list.
    """
    keywords = keywords or PROVIDER_KEYWORDS
    matches = {provider: [] for provider in keywords}

    for summary in model_summaries:
        model_id = (summary.get("modelId") or "").lower()
        for provider, needles in keywords.items():
            if any(needle in model_id for needle in needles):
                matches[provider].append(summary)

    for provider in matches:
        matches[provider].sort(key=lambda s: s.get("modelId", ""))

    return matches


def list_provider_names(model_summaries):
    """
    Return every distinct Bedrock "providerName" (e.g. "Anthropic",
    "Amazon", "DeepSeek", "Qwen", "Google") present in a region, sorted
    alphabetically. This is every provider Bedrock exposes here — a
    superset of the five providers PROVIDER_KEYWORDS specifically checks.
    """
    names = {summary.get("providerName") for summary in model_summaries}
    names.discard(None)
    return sorted(names)
