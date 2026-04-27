#!/usr/bin/env python3
"""Run a long-text extraction demo against the OPF HTTP service."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


DEMO_TEXT = """
Customer support case SR-2026-0419 was opened for a simulated user.

The requester is Alice Smith (private_person), reachable at
alice.smith@example.com (private_email) and +1-415-555-0187
(private_phone). Her mailing address is 123 Market Street, San Francisco,
CA 94105 (private_address). The account reference is ACCT-778899-001
(account_number).

During troubleshooting, the user pasted temporary portal credentials:
username mvandermeer2026 and password Redact-Th1s-L8r! (secret). The callback URL in the ticket is
https://example.com/private/reset?ticket=SR-2026-0419 (private_url).
The appointment date is 2026-04-27 (private_date).

This paragraph intentionally adds non-sensitive context so the model has to
separate ordinary business text from sensitive spans. The data above is fake
and exists only for demo and benchmark validation.
""".strip()


def post_json(base_url: str, path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="OPF service base URL. Default: http://localhost:8000",
    )
    parser.add_argument(
        "--include-source",
        action="store_true",
        help="Print the full source text returned by the API.",
    )
    args = parser.parse_args()

    try:
        start = time.perf_counter()
        result = post_json(
            args.base_url,
            "/extract",
            {"text": DEMO_TEXT, "include_text": True, "merge_adjacent": True},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
    except urllib.error.URLError as exc:
        print(f"Demo request failed: {exc}", file=sys.stderr)
        return 1

    output = {
        "client_latency_ms": round(elapsed_ms, 2),
        "server_latency_ms": round(result.get("latency_ms", 0.0), 2),
        "summary": result.get("summary", {}),
        "extracted_spans": result.get("extracted_spans", []),
    }
    if args.include_source:
        output["text"] = result.get("text", "")

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
