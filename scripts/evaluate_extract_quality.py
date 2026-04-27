#!/usr/bin/env python3
"""Evaluate extraction quality across baseline and post-processing profiles."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class TruthSpan:
    label: str
    text: str


SAMPLES = [
    {
        "name": "contact_ticket",
        "text": (
            "Please contact Alice Smith at alice.smith@example.com or "
            "+1-415-555-0187 before 2026-04-27."
        ),
        "truth": [
            TruthSpan("private_person", "Alice Smith"),
            TruthSpan("private_email", "alice.smith@example.com"),
            TruthSpan("private_phone", "+1-415-555-0187"),
            TruthSpan("private_date", "2026-04-27"),
        ],
    },
    {
        "name": "settlement_excerpt",
        "text": (
            "Mariella Vandermeer lives at 4412 Hillbrook Crescent, Apartment 7B, "
            "Stamford, Connecticut 06902. Email mariella.vandermeer@outlook.com. "
            "Wire account 987654321098, routing 021000021."
        ),
        "truth": [
            TruthSpan("private_person", "Mariella Vandermeer"),
            TruthSpan(
                "private_address",
                "4412 Hillbrook Crescent, Apartment 7B, Stamford, Connecticut 06902",
            ),
            TruthSpan("private_email", "mariella.vandermeer@outlook.com"),
            TruthSpan("account_number", "987654321098"),
            TruthSpan("account_number", "021000021"),
        ],
    },
    {
        "name": "logs_and_secrets",
        "text": (
            "POST https://portal.example.org/reset?token=qwerty failed for "
            "user bob@example.com. Rotate ghp_abcdefghijklmnopqrstuvwxyz012345 "
            "and password Redact-Th1s-L8r!."
        ),
        "truth": [
            TruthSpan("private_url", "https://portal.example.org/reset?token=qwerty"),
            TruthSpan("private_email", "bob@example.com"),
            TruthSpan("secret", "ghp_abcdefghijklmnopqrstuvwxyz012345"),
            TruthSpan("secret", "Redact-Th1s-L8r!"),
        ],
    },
    {
        "name": "no_pii",
        "text": "The system processed a normal status update with no private fields.",
        "truth": [],
    },
]


PROFILES = {
    "baseline": {},
    "merge": {"merge_adjacent": True, "merge_strategy": "label_aware"},
    "regex": {"enable_regex_backstop": True, "trim_punctuation": True},
    "hybrid": {
        "merge_adjacent": True,
        "merge_strategy": "label_aware",
        "enable_regex_backstop": True,
        "trim_punctuation": True,
    },
}


def locate_truth(text: str, truth: list[TruthSpan]) -> list[dict]:
    located = []
    cursor_by_text: dict[str, int] = {}
    for item in truth:
        start_at = cursor_by_text.get(item.text, 0)
        start = text.find(item.text, start_at)
        if start < 0:
            raise ValueError(f"Cannot locate truth span {item.text!r}")
        end = start + len(item.text)
        cursor_by_text[item.text] = end
        located.append(
            {"label": item.label, "start": start, "end": end, "text": item.text}
        )
    return located


def post_extract(base_url: str, text: str, profile: str, timeout: int) -> dict:
    payload = {"text": text, "include_text": True, **PROFILES[profile]}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/extract",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def overlaps(a: dict, b: dict) -> bool:
    return a["label"] == b["label"] and a["start"] < b["end"] and b["start"] < a["end"]


def exact_key(span: dict) -> tuple:
    return (span["label"], span["start"], span["end"])


def score_spans(truth: list[dict], pred: list[dict]) -> dict:
    truth_exact = {exact_key(span) for span in truth}
    pred_exact = {exact_key(span) for span in pred}
    exact_tp = len(truth_exact & pred_exact)

    matched_truth = set()
    matched_pred = set()
    for pred_idx, pred_span in enumerate(pred):
        for truth_idx, truth_span in enumerate(truth):
            if truth_idx in matched_truth:
                continue
            if overlaps(pred_span, truth_span):
                matched_truth.add(truth_idx)
                matched_pred.add(pred_idx)
                break

    return {
        "truth": len(truth),
        "pred": len(pred),
        "exact_tp": exact_tp,
        "overlap_tp": len(matched_pred),
        "tail_punctuation_errors": sum(
            1
            for span in pred
            if span["text"].endswith((".", ",", ";", ":", ")", "]", "}", "\"", "'"))
        ),
    }


def aggregate(rows: list[dict]) -> dict:
    truth = sum(row["truth"] for row in rows)
    pred = sum(row["pred"] for row in rows)
    exact_tp = sum(row["exact_tp"] for row in rows)
    overlap_tp = sum(row["overlap_tp"] for row in rows)

    def prf(tp: int) -> tuple[float, float, float]:
        precision = tp / pred if pred else 1.0
        recall = tp / truth if truth else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return precision, recall, f1

    exact_precision, exact_recall, exact_f1 = prf(exact_tp)
    overlap_precision, overlap_recall, overlap_f1 = prf(overlap_tp)
    latencies = [row["client_latency_ms"] for row in rows]
    server_latencies = [row["server_latency_ms"] for row in rows]
    return {
        "truth": truth,
        "pred": pred,
        "exact_precision": round(exact_precision, 4),
        "exact_recall": round(exact_recall, 4),
        "exact_f1": round(exact_f1, 4),
        "overlap_precision": round(overlap_precision, 4),
        "overlap_recall": round(overlap_recall, 4),
        "overlap_f1": round(overlap_f1, 4),
        "tail_punctuation_errors": sum(row["tail_punctuation_errors"] for row in rows),
        "client_latency_ms_avg": round(statistics.mean(latencies), 2),
        "server_latency_ms_avg": round(statistics.mean(server_latencies), 2),
    }


def evaluate_profile(base_url: str, profile: str, timeout: int) -> dict:
    rows = []
    details = []
    for sample in SAMPLES:
        truth = locate_truth(sample["text"], sample["truth"])
        start = time.perf_counter()
        result = post_extract(base_url, sample["text"], profile, timeout)
        client_latency_ms = (time.perf_counter() - start) * 1000.0
        pred = result.get("extracted_spans", [])
        row = score_spans(truth, pred)
        row["client_latency_ms"] = client_latency_ms
        row["server_latency_ms"] = float(result.get("latency_ms", 0.0))
        rows.append(row)
        details.append(
            {
                "name": sample["name"],
                "truth": truth,
                "pred": pred,
                "score": {
                    key: value
                    for key, value in row.items()
                    if key not in {"client_latency_ms", "server_latency_ms"}
                },
            }
        )
    return {
        "profile": profile,
        "options": PROFILES[profile],
        "summary": aggregate(rows),
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--profiles",
        default="baseline,merge,regex,hybrid",
        help="Comma-separated profiles. Default: baseline,merge,regex,hybrid",
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    profiles = [item.strip() for item in args.profiles.split(",") if item.strip()]
    invalid = [item for item in profiles if item not in PROFILES]
    if invalid:
        print(f"Invalid profiles: {invalid}", file=sys.stderr)
        return 2

    output = {"base_url": args.base_url, "profiles": []}
    try:
        for profile in profiles:
            result = evaluate_profile(args.base_url, profile, args.timeout)
            if not args.details:
                result.pop("details", None)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            output["profiles"].append(result)
    except urllib.error.URLError as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
