"""FastAPI server for OpenAI Privacy Filter (OPF).

Loads the model once at startup and keeps it in memory.
Exposes HTTP endpoints for PII redaction and extraction.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

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

    if merge_adjacent:
        spans = _merge_spans(spans, result.text)

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
            )
        )
    total_latency_ms = (time.perf_counter() - batch_start) * 1000.0
    return ExtractBatchResponse(results=results, total_latency_ms=total_latency_ms)
