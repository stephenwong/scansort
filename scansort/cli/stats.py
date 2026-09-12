"""Filing metrics, token usage, and cost analytics CLI subcommand handler."""

import argparse
import collections
import json
from typing import Any

from scansort.cli.args import CliArgs
from scansort.cli.history import load_history_records, safe_str
from scansort.core.config import get_default_app_dir
from scansort.core.constants import (
    HISTORY_JSONL_NAME,
    REVIEW_NEEDED_DIR,
    STATUS_COLLISION_RENAMED,
    STATUS_OCR_BACKFILLED,
    STATUS_REVIEWED,
    STATUS_SUCCESS,
)
from scansort.logging.cost import calculate_gemini_cost


def _calculate_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate statistics, token counts, and costs from audit records."""
    total_scans = len(records)
    status_counts: dict[str, int] = collections.defaultdict(int)
    folder_counts: dict[str, int] = collections.defaultdict(int)
    doc_type_counts: dict[str, int] = collections.defaultdict(int)

    prompt_tokens = 0
    candidates_tokens = 0
    total_cost_usd = 0.0

    for r in records:
        status = safe_str(r.get("status"), "UNKNOWN").upper()
        status_counts[status] += 1

        folder = r.get("destination_folder")
        if folder and not folder.lower().startswith(REVIEW_NEEDED_DIR.lower()):
            folder_counts[folder] += 1

        doc_type = r.get("document_type")
        if doc_type:
            doc_type_counts[doc_type] += 1

        # Token accumulation
        tokens_info = r.get("tokens")
        p_tok = 0
        c_tok = 0
        if isinstance(tokens_info, dict):
            p_tok = int(tokens_info.get("prompt", 0) or 0)
            c_tok = int(tokens_info.get("candidates", 0) or 0)
            prompt_tokens += p_tok
            candidates_tokens += c_tok

        # Cost calculation
        cost_entry = r.get("estimated_cost_usd")
        if isinstance(cost_entry, (int, float)):
            total_cost_usd += float(cost_entry)
        elif p_tok or c_tok:
            model = str(r.get("gemini_model") or "")
            total_cost_usd += calculate_gemini_cost(model, p_tok, c_tok)

    # Successful outcomes include direct filings, collision-renamed filings,
    # manual reviews, and OCR backfills; counting only the first two deflated
    # the rate whenever a maintenance/backfill run wrote audit records.
    success_count = sum(
        status_counts.get(status, 0)
        for status in (
            STATUS_SUCCESS,
            STATUS_COLLISION_RENAMED,
            STATUS_REVIEWED,
            STATUS_OCR_BACKFILLED,
        )
    )
    success_rate = (
        round((success_count / total_scans * 100.0), 1) if total_scans > 0 else 0.0
    )

    # Sort top folders and types
    top_folders = dict(
        sorted(folder_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    )
    top_types = dict(
        sorted(doc_type_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    )

    return {
        "total_scans": total_scans,
        "status_counts": dict(status_counts),
        "success_rate_pct": success_rate,
        "tokens": {
            "prompt": prompt_tokens,
            "candidates": candidates_tokens,
            "total": prompt_tokens + candidates_tokens,
        },
        "total_cost_usd": round(total_cost_usd, 6),
        "top_folders": top_folders,
        "top_document_types": top_types,
    }


def handle_stats(parsed: argparse.Namespace) -> int:
    """Handle 'stats' command to summarize filing activity, tokens, and estimated cost."""
    app_dir = get_default_app_dir()
    history_file = app_dir / HISTORY_JSONL_NAME

    records = load_history_records(history_file)
    if records is None:
        return 1
    if not records:
        print("No filing history found.")
        return 0

    metrics = _calculate_metrics(records)

    if CliArgs.from_namespace(parsed).json:
        print(json.dumps(metrics, indent=2))
        return 0

    print("================== ScanSort Filing Statistics ==================")
    print(f"Total Scans:        {metrics['total_scans']}")
    print(f"Success Rate:       {metrics['success_rate_pct']}%")
    print("-----------------------------------------------------------------")
    print("Breakdown by Status:")
    for status, count in metrics["status_counts"].items():
        print(f"  {status + ':':<18} {count}")
    print("-----------------------------------------------------------------")
    tokens = metrics["tokens"]
    print("Gemini API Consumption:")
    print(f"  Prompt Tokens:    {tokens['prompt']:,}")
    print(f"  Candidate Tokens: {tokens['candidates']:,}")
    print(f"  Total Tokens:     {tokens['total']:,}")
    print(f"  Estimated Cost:   ${metrics['total_cost_usd']:.6f} USD")

    if metrics["top_folders"]:
        print("-----------------------------------------------------------------")
        print("Top Destination Folders:")
        for folder, count in metrics["top_folders"].items():
            print(f"  {folder + ':':<24} {count}")

    if metrics["top_document_types"]:
        print("-----------------------------------------------------------------")
        print("Top Document Types:")
        for doc_type, count in metrics["top_document_types"].items():
            print(f"  {doc_type + ':':<24} {count}")

    print("=================================================================")
    return 0
