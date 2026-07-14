"""
FastAPI wrapper around the Bedrock availability check (main.run_check), so it
can run as a long-lived ECS service behind an ALB instead of a one-off CLI.

Served under the BASE_PATH prefix ("/check-bedrock") so this service can sit
alongside other services (e.g. EmailPOC's "/email_poc") behind the same host
without route collisions.

Routes:
    GET /health         -> liveness probe for the ALB target group (bare path,
                           conventional for health checks — not under BASE_PATH)
    GET /check-bedrock/ -> runs the check now and returns the result as JSON
"""

import json
import logging
import sys
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import config
from bedrock_client import BedrockAuthError
from main import run_check

# URL prefix this service is served under. Mirrors EmailPOC's BASE_PATH
# pattern so both projects can run behind the same host/ALB without their
# routes colliding.
BASE_PATH = "/check-bedrock"

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

app = FastAPI(title="Bedrock Availability Check")
router = APIRouter()


def _request_summary(request: Request, req_id):
    """
    Single-line, key=value summary of the incoming request - readable
    without parsing JSON, and short enough to stay on one line.

    X-Forwarded-For is a chain: each proxy in the path (Hong Kong Nginx,
    then the Singapore ALB) appends the IP it saw to the end, so the FIRST
    entry is the original client and later entries are each relay hop.
    """
    forwarded = request.headers.get("x-forwarded-for")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return (
        f"req_id={req_id} client_ip={client_ip} relay_chain=[{forwarded or '-'}] "
        f"method={request.method} path={request.url.path} "
        f"host={request.headers.get('host')} "
        f"user_agent=\"{request.headers.get('user-agent')}\" "
        f"referer={request.headers.get('referer') or '-'}"
    )


@app.get("/health")
def health():
    return PlainTextResponse("ok")


@router.get("/")
def check(request: Request):
    req_id = uuid.uuid4().hex[:8]
    logger.info("Request  %s", _request_summary(request, req_id))
    try:
        results, provider_names, total_models = run_check()
    except BedrockAuthError as exc:
        logger.info("Response req_id=%s error=%s", req_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

    response_body = {
        "region": config.AWS_REGION,
        "total_models_listed": total_models,
        "all_providers_in_region": provider_names,
        "providers": results,
        "summary": {provider: info["status"] for provider, info in results.items()},
    }
    logger.info("Response req_id=%s body=%s", req_id, json.dumps(response_body))
    return response_body


app.include_router(router, prefix=BASE_PATH)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
