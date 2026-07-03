"""
Region and environment configuration for the Bedrock availability POC.

Reads settings from environment variables / a local .env file (via python-dotenv).
Falls back to sane defaults when unset.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# AWS region to query. Defaults to us-east-1, which has the broadest
# Bedrock foundation-model coverage.
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Optional named AWS CLI profile. If unset, boto3 falls back to the default
# credential chain (env vars, shared credentials file, IAM role, SSO, etc.)
AWS_PROFILE = os.getenv("AWS_PROFILE") or None

# Prompt sent to every model we invoke as a "proof of life" check.
TEST_PROMPT = os.getenv("TEST_PROMPT", "Reply with exactly one word: OK")

# Max tokens to request on the test invocation. Kept tiny since we only need
# a one-word reply.
TEST_MAX_TOKENS = int(os.getenv("TEST_MAX_TOKENS", "16"))

# Where the JSON report is written.
REPORT_PATH = os.getenv("REPORT_PATH", "bedrock_availability_report.json")
