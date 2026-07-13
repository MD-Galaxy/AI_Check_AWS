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

from fastapi import APIRouter, FastAPI
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
logger.addHandler(logging.StreamHandler(sys.stdout))

app = FastAPI(title="Bedrock Availability Check")
router = APIRouter()


@app.get("/health")
def health():
    return PlainTextResponse("ok")


@router.get("/")
def check():
    try:
        results, provider_names, total_models = run_check()
    except BedrockAuthError as exc:
        logger.info("check failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

    response_body = {
        "region": config.AWS_REGION,
        "total_models_listed": total_models,
        "all_providers_in_region": provider_names,
        "providers": results,
        "summary": {provider: info["status"] for provider, info in results.items()},
    }
    logger.info("check response: %s", json.dumps(response_body))
    return response_body


app.include_router(router, prefix=BASE_PATH)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
