"""
Web wrapper around the Bedrock availability check (main.run_check), so it
can run as a long-lived ECS service behind an ALB instead of a one-off CLI.

Routes:
    GET /health -> liveness probe for the ALB target group
    GET /        -> runs the check now and returns the result as JSON
"""

import json
import logging
import sys

from flask import Flask, jsonify

import config
from bedrock_client import BedrockAuthError
from main import run_check

app = Flask(__name__)

logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))


@app.get("/health")
def health():
    return "ok", 200


@app.get("/")
def check():
    try:
        results, provider_names, total_models = run_check()
    except BedrockAuthError as exc:
        logger.info("check failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    response_body = {
        "region": config.AWS_REGION,
        "total_models_listed": total_models,
        "all_providers_in_region": provider_names,
        "providers": results,
        "summary": {provider: info["status"] for provider, info in results.items()},
    }
    logger.info("check response: %s", json.dumps(response_body))
    return jsonify(response_body)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
