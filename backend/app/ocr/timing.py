"""Structured timing logs for OCR processing stages."""

import json
import logging
import time
from contextlib import contextmanager
from typing import Iterator


def log_ocr_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    **fields: object,
) -> None:
    record = {"event": event, **fields}
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    logger.log(level, "%s %s", event, payload, extra=record)


@contextmanager
def timed_ocr_stage(
    logger: logging.Logger,
    stage: str,
    correlation_id: str,
    **fields: object,
) -> Iterator[dict[str, object]]:
    started_at = time.perf_counter()
    context = {
        "stage": stage,
        "correlation_id": correlation_id,
        "document_id": correlation_id,
        **fields,
    }
    log_ocr_event(logger, "OCR_STAGE_START", **context)
    finish_fields: dict[str, object] = {}
    try:
        yield finish_fields
    except Exception as exc:
        log_ocr_event(
            logger,
            "OCR_STAGE_ERROR",
            level=logging.ERROR,
            **context,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            exception_type=type(exc).__name__,
        )
        raise
    else:
        log_ocr_event(
            logger,
            "OCR_STAGE_FINISH",
            **context,
            **finish_fields,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
        )
