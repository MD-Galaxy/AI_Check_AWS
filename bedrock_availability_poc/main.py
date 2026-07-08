"""
Entry point: checks which AI model providers (Claude, DeepSeek, Qwen,
ChatGPT, Zhipu GLM) are available on this AWS account's Bedrock access,
actually invokes the ones that are listed, and prints/saves a summary.

Usage:
    python main.py
"""

import datetime
import json
import sys

from rich.console import Console
from rich.table import Table

import bedrock_client
import config
from bedrock_client import BedrockAuthError
from model_matcher import (
    PROVIDER_KEYWORDS,
    list_provider_names,
    match_providers,
    pick_invoke_candidate,
)

console = Console()

STATUS_ACCESSIBLE = "ACCESSIBLE"
STATUS_LISTED_FAILED = "LISTED BUT FAILED TO INVOKE"
STATUS_NOT_AVAILABLE = "NOT AVAILABLE ON BEDROCK"

STATUS_STYLE = {
    STATUS_ACCESSIBLE: "bold green",
    STATUS_LISTED_FAILED: "bold yellow",
    STATUS_NOT_AVAILABLE: "dim",
}


def print_summary_table(results):
    table = Table(title="Bedrock Model Availability Summary", show_lines=True)
    table.add_column("Provider", style="bold")
    table.add_column("Status")
    table.add_column("Detail")

    for provider, info in results.items():
        status = info["status"]
        style = STATUS_STYLE.get(status, "")

        if status == STATUS_ACCESSIBLE:
            detail = f"responded in {info['latency_seconds']}s: \"{info['response_text']}\""
            if info.get("used_inference_profile"):
                detail += f"\n(via inference profile {info['used_inference_profile']})"
        elif status == STATUS_LISTED_FAILED:
            detail = f"{info['error']}: {info['error_message']}"
        else:
            detail = "-"

        table.add_row(provider, f"[{style}]{status}[/{style}]", detail)

    console.print()
    console.print(table)


def print_provider_names(provider_names):
    console.print(
        f"\n[bold]All AI service providers available in this region "
        f"({len(provider_names)}):[/bold]"
    )
    console.print("  " + ", ".join(provider_names))


def write_json_report(results, list_check_count, provider_names):
    report = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "region": config.AWS_REGION,
        "total_models_listed": list_check_count,
        "all_providers_in_region": provider_names,
        "providers": results,
        "summary": {
            provider: info["status"] for provider, info in results.items()
        },
    }
    with open(config.REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    console.print(f"\nFull report written to [bold]{config.REPORT_PATH}[/bold]")


def print_final_summary_lines(results):
    console.print("\n[bold underline]SUMMARY[/bold underline]")
    width = max(len(p) for p in results) + 1
    for provider, info in results.items():
        status = info["status"]
        if status == STATUS_ACCESSIBLE:
            extra = f"(responded in {info['latency_seconds']}s: \"{info['response_text']}\")"
            if info.get("used_inference_profile"):
                extra += f" [via inference profile {info['used_inference_profile']}]"
        elif status == STATUS_LISTED_FAILED:
            extra = f"({info['error']})"
        else:
            extra = ""
        console.print(f"  {provider:<{width}} -> {status:<28} {extra}")


def main():
    console.print(f"[bold]Region:[/bold] {config.AWS_REGION}")
    console.print("Fetching foundation models visible to this account...\n")

    try:
        all_models = bedrock_client.list_foundation_models()
    except BedrockAuthError as exc:
        console.print(f"\n[bold red]Credential/permission error:[/bold red] {exc}")
        sys.exit(1)

    console.print(f"Found [bold]{len(all_models)}[/bold] total foundation models.\n")

    provider_names = list_provider_names(all_models)
    print_provider_names(provider_names)

    matches = match_providers(all_models, PROVIDER_KEYWORDS)
    results = {}
    for provider, model_list in matches.items():
        model_ids = [m.get("modelId") for m in model_list]

        if not model_list:
            results[provider] = {
                "listed": False,
                "matched_model_ids": [],
                "invoked_model_id": None,
                "status": STATUS_NOT_AVAILABLE,
                "latency_seconds": None,
                "response_text": None,
                "error": None,
                "error_message": None,
                "used_inference_profile": None,
            }
            continue

        invoke_model_id = pick_invoke_candidate(provider, model_list)
        console.print(f"[cyan]{provider}[/cyan]: listed on Bedrock ({len(model_ids)} model(s)), invoking `{invoke_model_id}`...")

        try:
            invocation = bedrock_client.invoke_model(invoke_model_id)
        except BedrockAuthError as exc:
            console.print(f"\n[bold red]Credential/permission error during invocation:[/bold red] {exc}")
            sys.exit(1)

        status = STATUS_ACCESSIBLE if invocation["ok"] else STATUS_LISTED_FAILED

        results[provider] = {
            "listed": True,
            "matched_model_ids": model_ids,
            "invoked_model_id": invoke_model_id,
            "status": status,
            "latency_seconds": invocation["latency_seconds"],
            "response_text": invocation["text"],
            "error": invocation["error"],
            "error_message": invocation["error_message"],
            "used_inference_profile": invocation["used_inference_profile"],
        }

    print_summary_table(results)
    print_final_summary_lines(results)
    write_json_report(results, len(all_models), provider_names)


if __name__ == "__main__":
    main()
