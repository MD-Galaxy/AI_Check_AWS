"""
Region and environment configuration for the Bedrock availability POC.

Reads settings from environment variables / a local .env file (via python-dotenv).
Falls back to sane defaults when unset.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# AWS region to query.
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

# Explicit AWS credentials, provided directly via .env. When both access key
# and secret are set, they take priority over everything else below.
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID") or None
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY") or None
# Only needed alongside temporary credentials (e.g. an assumed role / SSO
# session) — leave unset for a normal long-lived access key pair.
AWS_SESSION_TOKEN = os.getenv("AWS_SESSION_TOKEN") or None

# Optional named AWS CLI profile, used only if explicit access keys above
# are not set. If neither is set, boto3 falls back to its own default
# credential chain (env vars, shared credentials file, IAM role, SSO, etc.)
AWS_PROFILE = os.getenv("AWS_PROFILE") or None

# Prompt sent to every model we invoke as a "proof of life" check.
TEST_PROMPT = os.getenv("TEST_PROMPT", "Reply with exactly one word: OK")

# Max tokens to request on the test invocation. Kept tiny since we only need
# a one-word reply.
TEST_MAX_TOKENS = int(os.getenv("TEST_MAX_TOKENS", "16"))

# Where the JSON report is written.
REPORT_PATH = os.getenv("REPORT_PATH", "bedrock_availability_report.json")

# Direct Anthropic API key, for the "Manual Claude API Access" check — calls
# Claude via Anthropic's own API directly, bypassing AWS Bedrock entirely.
# Leave unset to skip this check.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or None

# Model used for the direct Anthropic API check.
ANTHROPIC_TEST_MODEL = os.getenv("ANTHROPIC_TEST_MODEL", "claude-sonnet-5")
