#!/usr/bin/env python3
"""Benchmark OPF extraction throughput with generated CPU-mode test data."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


SENSITIVE_BLOCK = (
    "Support note for Alice Smith. Email alice.smith@example.com. "
    "Phone +1-415-555-0187. Address 123 Market Street, San Francisco, CA 94105. "
    "Account ACCT-778899-001. Secret sk-test-1234567890abcdef. "
    "URL https://example.com/private/reset. Date 2026-04-27. "
    "The rest of this paragraph is ordinary operational context for benchmark "
    "testing and does not contain additional private data. "
)


@dataclass(frozen=True)
class SizeSpec:
    name: str
    bytes_count: int


def parse_size(value: str) -> SizeSpec:
    raw = value.strip().upper()
    multiplier = 1
    if raw.endswith("KB") or raw.endswith("K"):
        multiplier = 1024
        number = raw.removesuffix("KB").removesuffix("K")
    elif raw.endswith("MB") or raw.endswith("M"):
        multiplier = 1024 * 1024
        number = raw.removesuffix("MB").removesuffix("M")
    else:
        number = raw
    try:
        bytes_count = int(float(number) * multiplier)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid size: {value}") from exc
    if bytes_count <= 0:
        raise argparse.ArgumentTypeError(f"Size must be positive: {value}")
    return SizeSpec(name=value, bytes_count=bytes_count)


def make_text(target_bytes: int, seed: int) -> str:
    prefix = f"Benchmark chunk {seed}. "
    block = prefix + SENSITIVE_BLOCK
    repeated = block * max(1, math.ceil(target_bytes / len(block)))
    return repeated[:target_bytes]


def get_cpu_info() -> dict:
    model_name = None
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    model_name = line.split(":", 1)[1].strip()
                    break
    except OSError:
        model_name = platform.processor() or None

    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "cpu_model": model_name,
    }


def post_json(base_url: str, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/extract",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def benchmark_size(
    base_url: str,
    size: SizeSpec,
    chunk_bytes: int,
    timeout: int,
    warmup: bool,
    extract_options: dict,
) -> dict:
    if warmup:
        post_json(
            base_url,
            {
                "text": make_text(min(2048, size.bytes_count), -1),
                "include_text": False,
                **extract_options,
            },
            timeout,
        )

    total_spans = 0
    server_latencies = []
    requests = 0
    remaining = size.bytes_count
    start = time.perf_counter()

    while remaining > 0:
        current_size = min(chunk_bytes, remaining)
        text = make_text(current_size, requests)
        result = post_json(
            base_url,
            {"text": text, "include_text": False, **extract_options},
            timeout,
        )
        total_spans += len(result.get("extracted_spans", []))
        server_latencies.append(float(result.get("latency_ms", 0.0)))
        requests += 1
        remaining -= current_size

    elapsed_s = time.perf_counter() - start
    mb = size.bytes_count / (1024 * 1024)
    throughput = mb / elapsed_s if elapsed_s > 0 else 0.0
    throughput_bytes = size.bytes_count / elapsed_s if elapsed_s > 0 else 0.0
    avg_latency = statistics.mean(server_latencies) if server_latencies else 0.0
    p95_latency = (
        statistics.quantiles(server_latencies, n=20)[18]
        if len(server_latencies) >= 20
        else max(server_latencies, default=0.0)
    )

    return {
        "estimated": False,
        "size": size.name,
        "bytes": size.bytes_count,
        "chunk_bytes": chunk_bytes,
        "requests": requests,
        "spans": total_spans,
        "wall_time_s": round(elapsed_s, 3),
        "wall_time_h": round(elapsed_s / 3600, 4),
        "throughput_bytes_s": round(throughput_bytes, 2),
        "throughput_mb_s": round(throughput, 4),
        "avg_server_latency_ms": round(avg_latency, 2),
        "p95_server_latency_ms": round(p95_latency, 2),
    }


def estimate_size(size: SizeSpec, baseline: dict, chunk_bytes: int) -> dict:
    baseline_bytes = max(int(baseline["bytes"]), 1)
    baseline_time = max(float(baseline["wall_time_s"]), 0.001)
    scale = size.bytes_count / baseline_bytes
    estimated_wall_time = baseline_time * scale
    estimated_requests = math.ceil(size.bytes_count / chunk_bytes)
    return {
        "estimated": True,
        "size": size.name,
        "bytes": size.bytes_count,
        "chunk_bytes": chunk_bytes,
        "requests": estimated_requests,
        "spans": None,
        "wall_time_s": round(estimated_wall_time, 3),
        "wall_time_h": round(estimated_wall_time / 3600, 4),
        "throughput_bytes_s": baseline["throughput_bytes_s"],
        "throughput_mb_s": baseline["throughput_mb_s"],
        "avg_server_latency_ms": None,
        "p95_server_latency_ms": None,
        "estimate_basis": f"scaled from actual {baseline['size']} result",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="OPF service base URL. Default: http://localhost:8000",
    )
    parser.add_argument(
        "--sizes",
        default="1K,10K,1M,100M",
        help="Comma-separated benchmark sizes. Default: 1K,10K,1M,100M",
    )
    parser.add_argument(
        "--chunk-bytes",
        type=int,
        default=32768,
        help="Request chunk size in bytes. Default: 32768",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-request timeout in seconds. Default: 300",
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip one small warmup request before each size.",
    )
    parser.add_argument(
        "--estimate-over-bytes",
        type=int,
        default=0,
        help=(
            "Estimate sizes larger than this byte threshold from the largest "
            "actual run. Default 0 means run every size."
        ),
    )
    parser.add_argument(
        "--profile",
        choices=("baseline", "merge", "regex", "hybrid"),
        default="baseline",
        help="Extraction profile to benchmark. Default: baseline",
    )
    args = parser.parse_args()

    if args.chunk_bytes <= 0:
        print("--chunk-bytes must be positive", file=sys.stderr)
        return 2

    sizes = [parse_size(item) for item in args.sizes.split(",") if item.strip()]
    profiles = {
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
    extract_options = profiles[args.profile]
    results = []
    benchmark_start = time.perf_counter()
    for size in sizes:
        if args.estimate_over_bytes and size.bytes_count > args.estimate_over_bytes:
            actual_results = [item for item in results if not item.get("estimated")]
            if not actual_results:
                print(
                    "Cannot estimate before at least one actual benchmark result",
                    file=sys.stderr,
                )
                return 2
            baseline = max(actual_results, key=lambda item: int(item["bytes"]))
            result = estimate_size(size, baseline, args.chunk_bytes)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            results.append(result)
            continue

        try:
            result = benchmark_size(
                args.base_url,
                size,
                args.chunk_bytes,
                args.timeout,
                warmup=not args.no_warmup,
                extract_options=extract_options,
            )
        except urllib.error.URLError as exc:
            print(f"Benchmark failed for {size.name}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)

    output = {
        "base_url": args.base_url,
        "mode": "cpu-oriented HTTP benchmark",
        "profile": args.profile,
        "extract_options": extract_options,
        "machine": get_cpu_info(),
        "chunking_note": "Large inputs are split into chunks before calling /extract.",
        "estimation_note": (
            "Estimated rows are linear projections from the largest actual run; "
            "use them for capacity planning, not final SLA claims."
        ),
        "total_wall_time_s": round(time.perf_counter() - benchmark_start, 3),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
