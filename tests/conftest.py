"""Per-test log capture.

Every test writes its own log files under ``test_logs/`` (recreated each session):

    test_logs/<module>/<Class>.<test>.log     human-readable, DEBUG level, ends with the result
    test_logs/<module>/<Class>.<test>.jsonl   one JSON object per log record
    test_logs/_all.log                        every test, in run order
    test_logs/_summary.txt                    one line per test: outcome, duration, log lines

Console output (live, INFO) comes from ``log_cli`` in pyproject.toml.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

import pytest

from plotline.log import LOG_FORMAT

# A developer's .env may say LLM_MODE=live; tests never reach a model unless they inject one.
os.environ["LLM_MODE"] = "off"

LOG_DIR = Path(__file__).resolve().parent.parent / "test_logs"
_summary: list[str] = []


class _JsonlFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}",
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
            },
            ensure_ascii=False,
        )


def pytest_sessionstart(session):
    shutil.rmtree(LOG_DIR, ignore_errors=True)
    LOG_DIR.mkdir(parents=True)


def pytest_sessionfinish(session, exitstatus):
    if _summary:
        (LOG_DIR / "_summary.txt").write_text("\n".join(_summary) + "\n", encoding="utf-8")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    setattr(item, f"rep_{rep.when}", rep)
    return rep


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


@pytest.fixture(autouse=True)
def _capture_logs(request):
    node = request.node
    module = Path(str(node.fspath)).stem
    name = _safe(node.nodeid.split("::", 1)[1].replace("::", "."))
    folder = LOG_DIR / module
    folder.mkdir(parents=True, exist_ok=True)
    txt, jsonl = folder / f"{name}.log", folder / f"{name}.jsonl"

    handlers = [
        (logging.FileHandler(txt, encoding="utf-8"), logging.Formatter(LOG_FORMAT)),
        (logging.FileHandler(jsonl, encoding="utf-8"), _JsonlFormatter()),
        (logging.FileHandler(LOG_DIR / "_all.log", encoding="utf-8"), logging.Formatter(LOG_FORMAT)),
    ]
    for h, fmt in handlers:
        h.setLevel(logging.DEBUG)
        h.setFormatter(fmt)
    all_h = handlers[2][0]
    all_h.stream.write(f"\n===== {node.nodeid} =====\n")

    logger = logging.getLogger("plotline")
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    for h, _ in handlers:
        logger.addHandler(h)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        secs = time.perf_counter() - t0
        rep = getattr(node, "rep_call", None) or getattr(node, "rep_setup", None)
        outcome = rep.outcome.upper() if rep else "UNKNOWN"
        if rep is not None and rep.skipped:
            outcome = "SKIPPED"
        n_lines = len(txt.read_text(encoding="utf-8").splitlines()) if txt.exists() else 0
        end = f"RESULT: {outcome} in {secs * 1000:.1f} ms"
        logger.info(end)
        if rep is not None and rep.failed:
            logger.error("FAILURE DETAILS:\n%s", rep.longreprtext)
        for h, _ in handlers:
            logger.removeHandler(h)
            h.close()
        logger.setLevel(old_level)
        _summary.append(f"{outcome:8} {secs * 1000:8.1f} ms  {n_lines:4d} log lines  {node.nodeid}")
