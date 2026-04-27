"""FastAPI server for OpenAI Privacy Filter (OPF).

Loads the model once at startup and keeps it in memory.
Exposes HTTP endpoints for PII redaction and extraction.
"""

from __future__ import annotations

import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from opf._api import OPF, RedactionResult

logger = logging.getLogger("opf-server")

_redactor: OPF | None = None

SUPPORTED_LABELS = {
    "account_number",
    "private_address",
    "private_email",
    "private_person",
    "private_phone",
    "private_url",
    "private_date",
    "secret",
}

TAIL_PUNCTUATION = ".,;:)]}\"'"
TRIM_LABELS = {
    "account_number",
    "private_email",
    "private_phone",
    "private_url",
}
SECRET_TRIM_PUNCTUATION = ".,;:)]}\"'"

MAX_GAP_BY_LABEL = {
    "private_person": 3,
    "private_address": 3,
    "private_date": 3,
    "private_url": 2,
    "private_email": 0,
    "private_phone": 2,
    "account_number": 1,
    "secret": 2,
}
ALLOWED_CONNECTORS = set(" \t.-,/")
REGEX_BACKSTOP_LABELS = {"private_url", "secret", "account_number"}
LABEL_PRIORITY = {
    "private_email": 100,
    "private_url": 90,
    "secret": 80,
    "account_number": 70,
    "private_phone": 60,
    "private_date": 50,
    "private_address": 40,
    "private_person": 30,
}

URL_RE = re.compile(
    r"\bhttps?://"
    r"[A-Za-z0-9.\-]+(?:\.[A-Za-z]{2,63})"
    r"(?::\d{2,5})?"
    r"(?:/[^\s<>\"']*)?"
)
ACCOUNT_RE = re.compile(r"(?<![\d\-])\d{10,24}(?![\d\-])")
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"\bpk-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgho_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{12,}\b"),
    re.compile(
        r"\b(?=[A-Za-z0-9\-]*\d)(?=[A-Za-z0-9\-]*[A-Za-z])"
        r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+){2,}\b"
    ),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redactor
    device = os.environ.get("OPF_DEVICE", "cpu")
    output_mode = os.environ.get("OPF_OUTPUT_MODE", "typed")
    checkpoint = os.environ.get("OPF_CHECKPOINT", None)

    logger.info("Loading OPF model (device=%s, output_mode=%s) ...", device, output_mode)
    start = time.monotonic()
    _redactor = OPF(
        model=checkpoint,
        device=device,
        output_mode=output_mode,
    )
    _redactor.get_runtime()
    elapsed = time.monotonic() - start
    logger.info("Model loaded in %.1fs", elapsed)
    yield
    _redactor = None


app = FastAPI(
    title="OPF Privacy Filter Service",
    description="PII detection and redaction API powered by OpenAI Privacy Filter",
    version="0.1.0",
    lifespan=lifespan,
)


class RedactRequest(BaseModel):
    text: str = Field(..., description="Text to redact")


class RedactBatchRequest(BaseModel):
    texts: list[str] = Field(..., description="List of texts to redact")


class ExtractRequest(BaseModel):
    text: str = Field(..., description="Text to extract PII from")
    labels: list[str] | None = Field(
        default=None,
        description="Optional list of labels to include. Empty means all supported labels.",
    )
    include_text: bool = Field(
        default=True,
        description="Whether to include the sensitive source text in extracted spans.",
    )
    merge_adjacent: bool = Field(
        default=False,
        description="Whether to merge overlapping or adjacent spans with the same label.",
    )
    merge_strategy: Literal["overlap", "label_aware"] = Field(
        default="overlap",
        description="Span merge strategy. label_aware allows short same-label gaps.",
    )
    enable_regex_backstop: bool = Field(
        default=False,
        description="Whether to add high-confidence URL, secret, and account regex spans.",
    )
    trim_punctuation: bool = Field(
        default=False,
        description="Whether to conservatively trim trailing punctuation on structured spans.",
    )


class ExtractBatchRequest(BaseModel):
    texts: list[str] = Field(..., description="List of texts to extract PII from")
    labels: list[str] | None = Field(
        default=None,
        description="Optional list of labels to include. Empty means all supported labels.",
    )
    include_text: bool = Field(
        default=True,
        description="Whether to include the sensitive source text in extracted spans.",
    )
    merge_adjacent: bool = Field(
        default=False,
        description="Whether to merge overlapping or adjacent spans with the same label.",
    )
    merge_strategy: Literal["overlap", "label_aware"] = Field(
        default="overlap",
        description="Span merge strategy. label_aware allows short same-label gaps.",
    )
    enable_regex_backstop: bool = Field(
        default=False,
        description="Whether to add high-confidence URL, secret, and account regex spans.",
    )
    trim_punctuation: bool = Field(
        default=False,
        description="Whether to conservatively trim trailing punctuation on structured spans.",
    )


class SpanOut(BaseModel):
    label: str
    start: int
    end: int
    text: str
    placeholder: str


class ExtractSpanOut(BaseModel):
    label: str
    start: int
    end: int
    text: str


class RedactResponse(BaseModel):
    schema_version: int
    text: str
    redacted_text: str
    detected_spans: list[SpanOut]
    summary: dict
    warning: str | None = None
    latency_ms: float


class RedactTextOnlyResponse(BaseModel):
    redacted_text: str
    latency_ms: float


class RedactBatchResponse(BaseModel):
    results: list[RedactResponse]
    total_latency_ms: float


class ExtractResponse(BaseModel):
    schema_version: int
    text: str
    extracted_spans: list[ExtractSpanOut]
    summary: dict
    warning: str | None = None
    latency_ms: float


class ExtractBatchResponse(BaseModel):
    results: list[ExtractResponse]
    total_latency_ms: float


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", model_loaded=_redactor is not None)


def _build_response(text: str, result, latency_ms: float) -> RedactResponse:
    if isinstance(result, str):
        return RedactResponse(
            schema_version=0, text=text, redacted_text=result,
            detected_spans=[], summary={}, latency_ms=latency_ms,
        )
    assert isinstance(result, RedactionResult)
    return RedactResponse(
        schema_version=result.schema_version,
        text=result.text,
        redacted_text=result.redacted_text,
        detected_spans=[
            SpanOut(label=s.label, start=s.start, end=s.end,
                    text=s.text, placeholder=s.placeholder)
            for s in result.detected_spans
        ],
        summary=result.summary,
        warning=result.warning,
        latency_ms=latency_ms,
    )


def _validate_labels(labels: list[str] | None) -> set[str] | None:
    if labels is None:
        return None
    requested = set(labels)
    invalid = sorted(requested - SUPPORTED_LABELS)
    if invalid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported extraction label",
                "invalid_labels": invalid,
                "supported_labels": sorted(SUPPORTED_LABELS),
            },
        )
    return requested


def _merge_spans(spans: list[ExtractSpanOut], source_text: str) -> list[ExtractSpanOut]:
    if not spans:
        return []

    merged: list[ExtractSpanOut] = []
    for span in sorted(spans, key=lambda item: (item.start, item.end, item.label)):
        if (
            merged
            and span.label == merged[-1].label
            and span.start <= merged[-1].end
        ):
            previous = merged[-1]
            previous.end = max(previous.end, span.end)
            previous.text = source_text[previous.start:previous.end]
            continue
        merged.append(
            ExtractSpanOut(
                label=span.label,
                start=span.start,
                end=span.end,
                text=span.text,
            )
        )
    return merged


def _gap_is_mergeable(text: str, left_end: int, right_start: int, label: str) -> bool:
    if right_start < left_end:
        return False
    gap = text[left_end:right_start]
    if len(gap) > MAX_GAP_BY_LABEL.get(label, 1):
        return False
    if not gap:
        return True
    return all(ch in ALLOWED_CONNECTORS for ch in gap)


def _merge_spans_label_aware(
    spans: list[ExtractSpanOut], source_text: str
) -> list[ExtractSpanOut]:
    ordered = sorted(spans, key=lambda item: (item.start, item.end, item.label))
    if not ordered:
        return []

    merged = [
        ExtractSpanOut(
            label=ordered[0].label,
            start=ordered[0].start,
            end=ordered[0].end,
            text=ordered[0].text,
        )
    ]
    for span in ordered[1:]:
        previous = merged[-1]
        if (
            span.label == previous.label
            and _gap_is_mergeable(source_text, previous.end, span.start, span.label)
        ):
            previous.end = max(previous.end, span.end)
            previous.text = source_text[previous.start:previous.end]
            continue
        merged.append(
            ExtractSpanOut(
                label=span.label,
                start=span.start,
                end=span.end,
                text=span.text,
            )
        )
    return merged


def _overlaps(a: ExtractSpanOut, b: ExtractSpanOut) -> bool:
    return a.start < b.end and b.start < a.end


def _span_length(span: ExtractSpanOut) -> int:
    return span.end - span.start


def _trim_span(span: ExtractSpanOut, source_text: str) -> ExtractSpanOut:
    trim_chars = SECRET_TRIM_PUNCTUATION if span.label == "secret" else TAIL_PUNCTUATION
    if span.label not in TRIM_LABELS and span.label != "secret":
        return span

    end = span.end
    while end > span.start and source_text[end - 1] in trim_chars:
        end -= 1
    return ExtractSpanOut(
        label=span.label,
        start=span.start,
        end=end,
        text=source_text[span.start:end],
    )


def _trim_spans(
    spans: list[ExtractSpanOut], source_text: str
) -> list[ExtractSpanOut]:
    return [_trim_span(span, source_text) for span in spans]


def _detect_urls(text: str) -> list[ExtractSpanOut]:
    spans = []
    for match in URL_RE.finditer(text):
        raw = match.group(0)
        stripped = raw.rstrip(TAIL_PUNCTUATION)
        end = match.start() + len(stripped)
        spans.append(
            ExtractSpanOut(
                label="private_url",
                start=match.start(),
                end=end,
                text=text[match.start():end],
            )
        )
    return spans


def _detect_accounts(text: str) -> list[ExtractSpanOut]:
    return [
        ExtractSpanOut(
            label="account_number",
            start=match.start(),
            end=match.end(),
            text=match.group(0),
        )
        for match in ACCOUNT_RE.finditer(text)
    ]


def _detect_secrets(text: str) -> list[ExtractSpanOut]:
    spans = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            end = match.end()
            while end > match.start() and text[end - 1] in SECRET_TRIM_PUNCTUATION:
                end -= 1
            spans.append(
                ExtractSpanOut(
                    label="secret",
                    start=match.start(),
                    end=end,
                    text=text[match.start():end],
                )
            )
    return spans


def _regex_backstop_candidates(text: str) -> list[ExtractSpanOut]:
    candidates = []
    candidates.extend(_detect_urls(text))
    candidates.extend(_detect_secrets(text))
    candidates.extend(_detect_accounts(text))
    return candidates


def _apply_regex_backstop(
    spans: list[ExtractSpanOut], source_text: str
) -> list[ExtractSpanOut]:
    out = list(spans)
    for candidate in _regex_backstop_candidates(source_text):
        if candidate.label not in REGEX_BACKSTOP_LABELS:
            continue

        overlapping = [idx for idx, span in enumerate(out) if _overlaps(span, candidate)]
        if not overlapping:
            out.append(candidate)
            continue

        if any(out[idx].label == candidate.label for idx in overlapping):
            continue

        if _should_regex_override(candidate, [out[idx] for idx in overlapping]):
            for idx in sorted(overlapping, reverse=True):
                del out[idx]
            out.append(candidate)
            continue

        if _beats_all(candidate, [out[idx] for idx in overlapping]):
            for idx in sorted(overlapping, reverse=True):
                del out[idx]
            out.append(candidate)
    return sorted(out, key=lambda item: (item.start, item.end, item.label))


def _should_regex_override(
    candidate: ExtractSpanOut, overlapping: list[ExtractSpanOut]
) -> bool:
    if candidate.label == "private_url" and candidate.text.startswith(("http://", "https://")):
        return True
    if candidate.label == "secret" and candidate.text.startswith(
        ("sk-", "pk-", "ghp_", "gho_", "xoxb-", "xoxp-", "AKIA", "Bearer ")
    ):
        return True
    if candidate.label == "account_number":
        return any(
            span.label == "private_phone"
            and span.start >= candidate.start
            and span.end <= candidate.end
            for span in overlapping
        )
    return False


def _beats_all(candidate: ExtractSpanOut, spans: list[ExtractSpanOut]) -> bool:
    candidate_priority = LABEL_PRIORITY.get(candidate.label, 0)
    for span in spans:
        if _span_length(candidate) < _span_length(span):
            return False
        if (
            _span_length(candidate) == _span_length(span)
            and candidate_priority < LABEL_PRIORITY.get(span.label, 0)
        ):
            return False
    return True


def _summarize_spans(spans: list[ExtractSpanOut]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for span in spans:
        summary[span.label] = summary.get(span.label, 0) + 1
    return summary


def _build_extract_response(
    text: str,
    result,
    latency_ms: float,
    labels: set[str] | None,
    include_text: bool,
    merge_adjacent: bool,
    merge_strategy: Literal["overlap", "label_aware"],
    enable_regex_backstop: bool,
    trim_punctuation: bool,
) -> ExtractResponse:
    if isinstance(result, str):
        raise HTTPException(
            status_code=500,
            detail="Extraction requires OPF_OUTPUT_MODE=typed so detected spans are available.",
        )
    assert isinstance(result, RedactionResult)

    spans = [
        ExtractSpanOut(
            label=s.label,
            start=s.start,
            end=s.end,
            text=s.text,
        )
        for s in result.detected_spans
        if labels is None or s.label in labels
    ]

    if enable_regex_backstop:
        spans = _apply_regex_backstop(spans, result.text)

    if merge_adjacent and merge_strategy == "label_aware":
        spans = _merge_spans_label_aware(spans, result.text)
    elif merge_adjacent:
        spans = _merge_spans(spans, result.text)

    if trim_punctuation:
        spans = _trim_spans(spans, result.text)

    spans = [
        span for span in spans
        if labels is None or span.label in labels
    ]
    spans.sort(key=lambda span: (span.start, span.end, span.label))

    if not include_text:
        spans = [
            ExtractSpanOut(label=s.label, start=s.start, end=s.end, text="")
            for s in spans
        ]

    return ExtractResponse(
        schema_version=result.schema_version,
        text=text,
        extracted_spans=spans,
        summary=_summarize_spans(spans),
        warning=result.warning,
        latency_ms=latency_ms,
    )


@app.post("/redact", response_model=RedactResponse)
def redact(req: RedactRequest):
    if _redactor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    start = time.perf_counter()
    result = _redactor.redact(req.text)
    latency_ms = (time.perf_counter() - start) * 1000.0
    return _build_response(req.text, result, latency_ms)


@app.post("/redact/text", response_model=RedactTextOnlyResponse)
def redact_text_only(req: RedactRequest):
    if _redactor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    start = time.perf_counter()
    result = _redactor.redact(req.text)
    latency_ms = (time.perf_counter() - start) * 1000.0
    redacted = result.redacted_text if isinstance(result, RedactionResult) else str(result)
    return RedactTextOnlyResponse(redacted_text=redacted, latency_ms=latency_ms)


@app.post("/redact/batch", response_model=RedactBatchResponse)
def redact_batch(req: RedactBatchRequest):
    if _redactor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    batch_start = time.perf_counter()
    results = []
    for text in req.texts:
        start = time.perf_counter()
        result = _redactor.redact(text)
        latency_ms = (time.perf_counter() - start) * 1000.0
        results.append(_build_response(text, result, latency_ms))
    total_latency_ms = (time.perf_counter() - batch_start) * 1000.0
    return RedactBatchResponse(results=results, total_latency_ms=total_latency_ms)


@app.post("/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest):
    if _redactor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    labels = _validate_labels(req.labels)
    start = time.perf_counter()
    result = _redactor.redact(req.text)
    latency_ms = (time.perf_counter() - start) * 1000.0
    return _build_extract_response(
        text=req.text,
        result=result,
        latency_ms=latency_ms,
        labels=labels,
        include_text=req.include_text,
        merge_adjacent=req.merge_adjacent,
        merge_strategy=req.merge_strategy,
        enable_regex_backstop=req.enable_regex_backstop,
        trim_punctuation=req.trim_punctuation,
    )


@app.post("/extract/batch", response_model=ExtractBatchResponse)
def extract_batch(req: ExtractBatchRequest):
    if _redactor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    labels = _validate_labels(req.labels)
    batch_start = time.perf_counter()
    results = []
    for text in req.texts:
        start = time.perf_counter()
        result = _redactor.redact(text)
        latency_ms = (time.perf_counter() - start) * 1000.0
        results.append(
            _build_extract_response(
                text=text,
                result=result,
                latency_ms=latency_ms,
                labels=labels,
                include_text=req.include_text,
                merge_adjacent=req.merge_adjacent,
                merge_strategy=req.merge_strategy,
                enable_regex_backstop=req.enable_regex_backstop,
                trim_punctuation=req.trim_punctuation,
            )
        )
    total_latency_ms = (time.perf_counter() - batch_start) * 1000.0
    return ExtractBatchResponse(results=results, total_latency_ms=total_latency_ms)
