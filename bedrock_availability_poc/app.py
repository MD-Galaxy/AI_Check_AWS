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
import uuid

from flask import Flask, jsonify, request

import config
from bedrock_client import BedrockAuthError
from main import run_check

app = Flask(__name__)

logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S %z"))
logger.addHandler(_handler)

# NOTE: the ECS/CloudWatch log driver ships each stdout LINE as its own
# separate log event - a multi-line message gets shredded into dozens of
# unrelated-looking events. So every log call here must stay on one line;
# a short req_id ties the "request" and "response" lines for the same
# call together when scanning the log group.


def _request_summary(req_id):
    """
    Single-line, key=value summary of the incoming request - readable
    without parsing JSON, and short enough to stay on one line.

    X-Forwarded-For is a chain: each proxy in the path (Hong Kong Nginx,
    then the Singapore ALB) appends the IP it saw to the end, so the FIRST
    entry is the original client and later entries are each relay hop.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    client_ip = forwarded.split(",")[0].strip() if forwarded else request.remote_addr
    return (
        f"req_id={req_id} client_ip={client_ip} relay_chain=[{forwarded or '-'}] "
        f"method={request.method} path={request.full_path.rstrip('?')} "
        f"host={request.headers.get('Host')} "
        f"user_agent=\"{request.headers.get('User-Agent')}\" "
        f"referer={request.headers.get('Referer') or '-'}"
    )


@app.get("/health")
def health():
    return "ok", 200


@app.get("/")
def check():
    req_id = uuid.uuid4().hex[:8]
    logger.info("Request  %s", _request_summary(req_id))
    try:
        results, provider_names, total_models = run_check()
    except BedrockAuthError as exc:
        logger.info("Response req_id=%s error=%s", req_id, exc)
        return jsonify({"error": str(exc)}), 500

    response_body = {
        "region": config.AWS_REGION,
        "total_models_listed": total_models,
        "all_providers_in_region": provider_names,
        "providers": results,
        "summary": {provider: info["status"] for provider, info in results.items()},
    }
    logger.info("Response req_id=%s body=%s", req_id, json.dumps(response_body))
    return jsonify(response_body)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
