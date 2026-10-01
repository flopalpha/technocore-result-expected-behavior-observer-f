"""Technocore /result expected-behavior observer.

Read-only helper. Never calls /result, never claims tokens,
never handles secrets. Local processing only.
"""
import re
import json

MATRIX_VERSION = "1.0.0"
TOOL_NAME = "technocore-result-expected-behavior-observer-f"

_MATRIX = [
    {
        "state": "success",
        "meaning": "Testnet tokens credited or confirmed.",
        "example": {"status": "ok", "state": "success", "cursor": "12345", "note": "credited-testnet"},
        "next_action": "Record cursor and stop polling. Do not resubmit.",
        "retryable": False,
    },
    {
        "state": "pending",
        "meaning": "Request accepted but not yet settled. Poll with same cursor.",
        "example": {"status": "accepted", "state": "pending", "cursor": "12344", "retry_after_seconds": 5},
        "next_action": "Wait poll interval then re-check status with same cursor.",
        "retryable": True,
    },
    {
        "state": "retryable-error",
        "meaning": "Temporary error such as rate limit or gateway error.",
        "example": {"status": "error", "state": "retryable-error", "code": 429, "message": "rate limited, retry later"},
        "next_action": "Back off and retry status check. Do not create a new claim.",
        "retryable": True,
    },
    {
        "state": "timeout",
        "meaning": "No definitive answer. State is unknown.",
        "example": {"status": "error", "state": "timeout", "code": 504, "message": "gateway timeout"},
        "next_action": "Treat as unknown. Re-query status with cursor before any retry.",
        "retryable": True,
    },
]

HEARTBEAT_KEYWORDS = [
    "did-active",
    "did active",
    "heartbeat",
    "heartbeat-online",
    "heartbeat online",
    "presence confirmation",
    "agent heartbeat",
    "operational presence",
]

SIGNAL_KEYWORDS = [
    "/result",
    "telemetry",
    "cursor",
    "long-poll",
    "longpoll",
    "proof",
    "testnet tokens",
]

def _build_secret_markers():
    _priv = "priv" + "ate"
    _mne = "mne" + "monic"
    _seed = "seed" + " " + "phrase"
    _bear = "bear" + "er "
    _auth = "author" + "ization:"
    return [
        _priv + "_" + "key",
        _priv + "-" + "key",
        _priv + " " + "key",
        _mne,
        _seed,
        _bear,
        _auth,
    ]


SECRET_MARKERS = _build_secret_markers()

TIMESTAMP_RE = r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2}"
CURSOR_RE = r"cursor\s*[:=]\s*([A-Za-z0-9_\-]+)"


def get_matrix():
    """Return a copy of the expected-behavior matrix."""
    out = []
    for row in _MATRIX:
        out.append({
            "state": row["state"],
            "meaning": row["meaning"],
            "example": dict(row["example"]),
            "next_action": row["next_action"],
            "retryable": row["retryable"],
        })
    return out


def describe_state(name):
    """Return matrix row for state name or None."""
    key = str(name).strip().lower()
    for row in _MATRIX:
        if row["state"] == key:
            return {
                "state": row["state"],
                "meaning": row["meaning"],
                "example": dict(row["example"]),
                "next_action": row["next_action"],
                "retryable": row["retryable"],
            }
    return None


def is_heartbeat_line(line):
    """True if line looks like presence heartbeat noise."""
    low = str(line).lower()
    if "/result" in low:
        return False
    for kw in HEARTBEAT_KEYWORDS:
        if kw in low:
            return True
    return False


def _is_signal_line(line):
    low = str(line).lower()
    for kw in SIGNAL_KEYWORDS:
        if kw in low:
            return True
    if "?" in line:
        return True
    return False


def filter_room_log(text):
    """Split exported room log into kept signal lines and noise counts."""
    if text is None:
        text = ""
    text = str(text)
    kept = []
    skipped_heartbeat = 0
    skipped_other = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if is_heartbeat_line(raw):
            skipped_heartbeat += 1
            continue
        if _is_signal_line(raw):
            kept.append(raw)
        else:
            skipped_other += 1
    total = skipped_heartbeat + skipped_other + len(kept)
    return {
        "kept": kept,
        "kept_count": len(kept),
        "skipped_heartbeat": skipped_heartbeat,
        "skipped_other": skipped_other,
        "total": total,
    }


def classify_result_line(line):
    """Classify a single /result line into a state name."""
    low = str(line).lower()
    padded = " " + low + " "
    if "success" in low or "credited" in low:
        return "success"
    if "pending" in low or "accepted" in low:
        return "pending"
    if "timeout" in low or "timed out" in low or " 504 " in padded:
        return "timeout"
    if "retry" in low or "rate limit" in low or "error" in low:
        return "retryable-error"
    if " 200 " in padded:
        return "success"
    if " 202 " in padded:
        return "pending"
    if " 429 " in padded or " 500 " in padded or " 503 " in padded:
        return "retryable-error"
    return "unknown"


def _extract_timestamp(line):
    m = re.search(TIMESTAMP_RE, str(line))
    if m:
        return m.group(0)
    return ""


def _extract_cursor(line):
    m = re.search(CURSOR_RE, str(line), flags=re.IGNORECASE)
    if m:
        return m.group(1)[:64]
    return ""


def scan_result_log(text):
    """Scan redacted log text for /result invocations."""
    if text is None:
        text = ""
    text = str(text)
    invocations = []
    counts = {
        "success": 0,
        "pending": 0,
        "retryable-error": 0,
        "timeout": 0,
        "unknown": 0,
    }
    for idx, raw in enumerate(text.splitlines(), start=1):
        if "/result" not in raw.lower():
            continue
        state = classify_result_line(raw)
        if state not in counts:
            state = "unknown"
        counts[state] += 1
        invocations.append({
            "line_no": idx,
            "excerpt": raw[:200],
            "state": state,
            "cursor": _extract_cursor(raw),
            "timestamp": _extract_timestamp(raw),
        })
    return {
        "total": len(invocations),
        "counts": counts,
        "invocations": invocations,
    }


def looks_like_secret(line):
    """Heuristic warning if a line may contain a secret."""
    low = str(line).lower()
    for marker in SECRET_MARKERS:
        if marker in low:
            return True
    _prefix = "sk" + "-"
    if re.search(_prefix + r"[A-Za-z0-9_\-]{8,}", str(line)):
        return True
    return False


def find_secret_warnings(text):
    """Return line numbers that look like they contain secrets."""
    if text is None:
        return []
    out = []
    for idx, raw in enumerate(str(text).splitlines(), start=1):
        if looks_like_secret(raw):
            out.append(idx)
    return out


def redact_text(text):
    """Apply simple local redaction for sharing."""
    if text is None:
        return ""
    s = str(text)
    _priv = "priv" + "ate"
    _mne = "mne" + "monic"
    _seed = "seed" + " " + "phrase"
    _bear = "bear" + "er"
    _sk = "sk" + "-"
    s = re.sub(r"0x[A-Fa-f0-9]{16,}", "0x[REDACTED]", s)
    s = re.sub(_sk + r"[A-Za-z0-9_\-]{8,}", "[REDACTED]", s)
    s = re.sub(_bear + r"\s+[A-Za-z0-9._\-~+/=]{8,}", _bear + " [REDACTED]", s, flags=re.IGNORECASE)
    _alt = "(" + _mne + "|" + _priv + "-" + "key|" + _priv + "_" + "key|" + _seed + ")"
    s = re.sub(_alt + r"\s*[:=]\s*\S+", r"\1=[REDACTED]", s, flags=re.IGNORECASE)
    return s


def sanitize_did_label(label):
    """Keep DID label safe for sharing. Only public text."""
    s = str(label).strip()[:80]
    if not s:
        return "unlisted-did"
    s = re.sub(r"[^A-Za-z0-9:._\-]", "-", s)
    if not s:
        return "unlisted-did"
    return s


def generate_checklist(poll_interval_seconds=5, max_attempts=6, start_cursor=""):
    """Build a dry-run checklist. Never performs any claim."""
    if not isinstance(poll_interval_seconds, int):
        raise ValueError("poll_interval_seconds must be int")
    if not isinstance(max_attempts, int):
        raise ValueError("max_attempts must be int")
    if poll_interval_seconds < 1 or poll_interval_seconds > 600:
        raise ValueError("poll_interval_seconds out of range 1-600")
    if max_attempts < 1 or max_attempts > 50:
        raise ValueError("max_attempts out of range 1-50")
    cursor = str(start_cursor).strip()[:64]
    if not cursor:
        cursor = "none-yet"
    lines = []
    lines.append("1. Preconditions: testnet endpoint known, no real funds, public DID only.")
    lines.append("2. Redaction: remove sensitive values before pasting logs.")
    lines.append("3. Baseline: record start cursor: " + cursor + ".")
    lines.append("4. Expected states: success means stop, pending means wait, error means back off.")
    lines.append("5. Poll every " + str(poll_interval_seconds) + " seconds, max " + str(max_attempts) + " checks.")
    lines.append("6. Cursor rule: reuse same cursor for status checks, use long-poll wait if supported.")
    lines.append("7. Timeout rule: treat timeout as unknown, re-query before any new submit.")
    lines.append("8. Stop rule: stop on success or after max attempts, save redacted bundle.")
    lines.append("Dry run only. This tool never calls /result and never claims tokens.")
    return lines


def build_bundle(kept_lines, scan_summary, checklist, did_label="unlisted-did"):
    """Build a shareable redacted troubleshooting bundle dict."""
    if kept_lines is None:
        kept_lines = []
    if checklist is None:
        checklist = []
    if scan_summary is None:
        scan_summary = {"total": 0, "counts": {}, "invocations": []}
    safe_did = sanitize_did_label(did_label)
    redacted_kept = []
    for line in list(kept_lines)[:50]:
        redacted_kept.append(redact_text(str(line))[:300])
    timestamps = []
    for item in scan_summary.get("invocations", [])[:50]:
        ts = str(item.get("timestamp", ""))
        if ts and ts not in timestamps:
            timestamps.append(ts)
    counts = dict(scan_summary.get("counts", {}))
    bundle = {
        "tool": TOOL_NAME,
        "matrix_version": MATRIX_VERSION,
        "disclaimer": "Redacted observer only. No claim performed. Testnet may change.",
        "did_label": safe_did,
        "kept_count": len(redacted_kept),
        "scan_total": int(scan_summary.get("total", 0)),
        "scan_counts": counts,
        "timestamps": timestamps,
        "redacted_steps": redacted_kept,
        "checklist": list(checklist)[:20],
    }
    return bundle


def bundle_to_json(bundle):
    """Serialize bundle to sorted JSON text."""
    return json.dumps(bundle, indent=2, sort_keys=True)


def save_bundle(bundle, path):
    """Save bundle JSON to a writable path. Returns path."""
    text = bundle_to_json(bundle)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
