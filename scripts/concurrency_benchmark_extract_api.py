#!/usr/bin/env python3
"""Run concurrent extraction benchmarks and optionally sample NVIDIA GPU load."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request


SAMPLE_TEXT = (
    "Settlement notice for Mariella Vandermeer, email "
    "mariella.vandermeer@outlook.com, phone +1-203-555-0142, address "
    "4412 Hillbrook Crescent, Apartment 7B, Stamford, Connecticut 06902. "
    "Wire account 987654321098 routing 021000021. Temporary password "
    "Redact-Th1s-L8r! and portal https://portal.example.org/reset?ticket=abc."
)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1)
    return ordered[idx]


def post_extract(base_url: str, text: str, timeout: int) -> tuple[bool, float, str | None]:
    payload = {
        "text": text,
        "include_text": False,
        "merge_adjacent": True,
        "merge_strategy": "label_aware",
        "enable_regex_backstop": True,
        "trim_punctuation": True,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/extract",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True, (time.perf_counter() - start) * 1000.0, None
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, (time.perf_counter() - start) * 1000.0, str(exc)


def gpu_sample_loop(stop: threading.Event, samples: list[dict], interval: float) -> None:
    query = (
        "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total "
        "--format=csv,noheader,nounits"
    )
    while not stop.is_set():
        try:
            output = subprocess.check_output(
                query,
                shell=True,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).strip()
        except Exception:
            return
        if output:
            line = output.splitlines()[0]
            parts = [item.strip() for item in line.split(",")]
            if len(parts) >= 3:
                samples.append(
                    {
                        "gpu_util_pct": float(parts[0]),
                        "memory_used_mb": float(parts[1]),
                        "memory_total_mb": float(parts[2]),
                    }
                )
        stop.wait(interval)


def run_level(
    base_url: str,
    concurrency: int,
    duration_s: int,
    timeout: int,
    text_multiplier: int,
    sample_gpu: bool,
) -> dict:
    text = (SAMPLE_TEXT + "\n") * text_multiplier
    deadline = time.perf_counter() + duration_s
    latencies: list[float] = []
    errors: list[str] = []
    completed = 0
    lock = threading.Lock()
    gpu_samples: list[dict] = []
    stop_gpu = threading.Event()
    gpu_thread = None

    if sample_gpu:
        gpu_thread = threading.Thread(
            target=gpu_sample_loop,
            args=(stop_gpu, gpu_samples, 1.0),
            daemon=True,
        )
        gpu_thread.start()

    def worker() -> None:
        nonlocal completed
        while time.perf_counter() < deadline:
            ok, latency_ms, err = post_extract(base_url, text, timeout)
            with lock:
                completed += 1
                latencies.append(latency_ms)
                if not ok and err is not None:
                    errors.append(err)

    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker) for _ in range(concurrency)]
        concurrent.futures.wait(futures)
    elapsed_s = time.perf_counter() - start

    if gpu_thread is not None:
        stop_gpu.set()
        gpu_thread.join(timeout=2)

    success = completed - len(errors)
    gpu_summary = {}
    if gpu_samples:
        utils = [item["gpu_util_pct"] for item in gpu_samples]
        mem = [item["memory_used_mb"] for item in gpu_samples]
        total = gpu_samples[-1]["memory_total_mb"]
        gpu_summary = {
            "gpu_util_avg_pct": round(statistics.mean(utils), 2),
            "gpu_util_max_pct": round(max(utils), 2),
            "gpu_memory_max_mb": round(max(mem), 2),
            "gpu_memory_total_mb": round(total, 2),
        }

    return {
        "concurrency": concurrency,
        "duration_s": duration_s,
        "text_bytes": len(text.encode("utf-8")),
        "completed": completed,
        "success": success,
        "errors": len(errors),
        "rps": round(success / elapsed_s, 4) if elapsed_s else 0.0,
        "latency_ms_avg": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "latency_ms_p50": round(percentile(latencies, 50), 2),
        "latency_ms_p95": round(percentile(latencies, 95), 2),
        "latency_ms_p99": round(percentile(latencies, 99), 2),
        **gpu_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--levels", default="1,2,4,8")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--text-multiplier", type=int, default=1)
    parser.add_argument("--sample-gpu", action="store_true")
    args = parser.parse_args()

    levels = [int(item) for item in args.levels.split(",") if item.strip()]
    results = []
    for level in levels:
        result = run_level(
            args.base_url,
            level,
            args.duration,
            args.timeout,
            args.text_multiplier,
            args.sample_gpu,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)

    print(json.dumps({"base_url": args.base_url, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
