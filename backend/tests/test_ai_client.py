# tests/test_ai_client.py
# Tests for the subprocess-isolated waste-AI adapter (backend/ai_client.py).
#
# NO test calls Gemini. The adapter is exercised two ways:
#   1. REAL subprocess spawning against a stdlib-only FAKE AI source directory
#      (waste_pipeline.py / cleanup_verifier.py shims mirroring the real AI's
#      import structure) — proves the worker protocol end to end.
#   2. subprocess.run monkeypatching — to inspect the transport envelope
#      (base64 image, stdin JSON) and simulate timeout / garbage / crashes
#      without depending on AI-side behavior.
#
# The fake AI source also verifies the adapter does NOT modify ai/: it exists
# only inside tmp_path and points WASTE_AI_SRC at itself via monkeypatched env.

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ai_client  # noqa: E402


# ---------------------------------------------------------------------------
# Fake AI source (stdlib only) — mirrors the real AI's import structure
# ---------------------------------------------------------------------------
FAKE_WASTE_PIPELINE = '''
"""Fake of ai/src/waste_pipeline.py — echoes inputs, emits a realistic result."""
def process_waste_image(image_bytes, mime_type="image/jpeg",
                        additional_context=None, location=None,
                        prior_reports_at_location=0):
    return {
        "image_usable": True,
        "unusable_reason": None,
        "waste_type": "sanitary",
        "waste_type_confidence": 0.82,
        "severity": "dump_scale",
        "severity_confidence": 0.91,
        "reasoning": "fake reasoning",
        "follow_up_question": None,
        "location": location,
        "prior_reports_at_location": prior_reports_at_location,
        "recurring_flag": prior_reports_at_location >= 3,
        "escalate_to_authority": True,
        "needs_human_review": False,
        "review_reasons": [],
        "disposal_guidance": None,
        "errors": [],
        "_echo_len": len(image_bytes),
    }
'''

FAKE_CLEANUP_VERIFIER = '''
"""Fake of ai/src/cleanup_verifier.py."""
def verify_cleanup(before_image_bytes, after_image_bytes,
                   before_mime="image/jpeg", after_mime="image/jpeg"):
    return {
        "after_image_usable": True,
        "unusable_reason": None,
        "cleanup_appears_complete": True,
        "confidence": 0.88,
        "reasoning": "fake comparison",
        "admin_review_recommended": False,
        "_before_len": len(before_image_bytes),
        "_after_len": len(after_image_bytes),
    }
'''

# A noisy variant that spams stderr before emitting the JSON envelope —
# proves the parent parses stdout only.
NOISY_WASTE_PIPELINE = '''
import sys
def process_waste_image(image_bytes, mime_type="image/jpeg", additional_context=None,
                        location=None, prior_reports_at_location=0):
    sys.stderr.write("[transformers] loading model...\\n")
    sys.stderr.write("progress: 50%\\n")
    return {
        "image_usable": True, "unusable_reason": None,
        "waste_type": "wet", "waste_type_confidence": 0.9,
        "severity": "domestic", "severity_confidence": 0.9,
        "reasoning": "noisy", "follow_up_question": None,
        "location": location, "prior_reports_at_location": prior_reports_at_location,
        "recurring_flag": False, "escalate_to_authority": False,
        "needs_human_review": False, "review_reasons": [],
        "disposal_guidance": "ok", "errors": [],
    }
'''


@pytest.fixture
def fake_ai_src(tmp_path):
    """A stdlib-only stand-in for ai/src on the waste-image-classification branch."""
    src = tmp_path / "fake_ai_src"
    src.mkdir()
    (src / "waste_pipeline.py").write_text(FAKE_WASTE_PIPELINE, encoding="utf-8")
    (src / "cleanup_verifier.py").write_text(FAKE_CLEANUP_VERIFIER, encoding="utf-8")
    return src


@pytest.fixture
def assist_env(fake_ai_src, monkeypatch):
    monkeypatch.setenv("WASTE_AI_MODE", "assist")
    monkeypatch.setenv("WASTE_AI_SRC", str(fake_ai_src))
    monkeypatch.setenv("WASTE_AI_TIMEOUT_S", "120")
    return fake_ai_src


# ---------------------------------------------------------------------------
# 1. Successful JSON response (real subprocess against the fake AI source)
# ---------------------------------------------------------------------------
def test_successful_real_subprocess_call(assist_env):
    outcome = ai_client.analyze_waste_image(
        image_bytes=b"fake-jpeg-bytes",
        mime_type="image/jpeg",
        additional_context="here for two weeks",
        location={"lat": 12.97, "lng": 77.59},
        prior_reports_at_location=3,
    )
    assert outcome["success"] is True
    assert outcome["error"] is None
    result = outcome["result"]
    assert result["waste_type"] == "sanitary"      # verbatim, unmapped
    assert result["severity"] == "dump_scale"      # verbatim, unmapped
    assert result["escalate_to_authority"] is True
    assert result["recurring_flag"] is True
    assert result["prior_reports_at_location"] == 3
    assert result["location"] == {"lat": 12.97, "lng": 77.59}
    assert result["_echo_len"] == len(b"fake-jpeg-bytes")
    assert isinstance(outcome["latency_ms"], int) and outcome["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# 9. Image bytes encoded/decoded correctly through the transport
# ---------------------------------------------------------------------------
def test_image_bytes_base64_roundtrip(assist_env):
    payload = bytes(range(256)) * 4   # all byte values, big enough to catch truncation
    outcome = ai_client.analyze_waste_image(payload, prior_reports_at_location=0)
    assert outcome["success"] is True
    assert outcome["result"]["_echo_len"] == len(payload)
    assert outcome["result"]["_echo_len"] == 1024


# ---------------------------------------------------------------------------
# Transport envelope inspection (monkeypatched subprocess.run)
# ---------------------------------------------------------------------------
def test_subprocess_receives_base64_image_in_stdin_json(monkeypatch, assist_env):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps({"ok": True, "task": "analyze", "result": {"image_usable": True}}).encode()
        stderr = b""

    def fake_run(argv, input, **kwargs):
        captured["argv"] = argv
        captured["stdin"] = json.loads(input.decode("utf-8"))
        return FakeCompleted()

    monkeypatch.setattr(ai_client.subprocess, "run", fake_run)
    raw = b"\xff\xd8\xff\xfa-binary"
    ai_client.analyze_waste_image(raw, mime_type="image/png")

    assert captured["stdin"]["image_b64"] == base64.b64encode(raw).decode("ascii")
    assert captured["stdin"]["mime_type"] == "image/png"
    assert captured["stdin"]["prior_reports_at_location"] == 0
    # raw bytes must never appear in argv
    assert all(raw not in str(arg).encode() for arg in captured["argv"])
    assert captured["argv"][0] == sys.executable and "ai_worker.py" in captured["argv"][1]


def test_stderr_does_not_corrupt_json_parsing(fake_ai_src, monkeypatch):
    """A chatty child (transformers-style progress bars on stderr) still parses."""
    (fake_ai_src / "waste_pipeline.py").write_text(NOISY_WASTE_PIPELINE, encoding="utf-8")
    monkeypatch.setenv("WASTE_AI_MODE", "assist")
    monkeypatch.setenv("WASTE_AI_SRC", str(fake_ai_src))

    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is True
    assert outcome["result"]["waste_type"] == "wet"
    assert outcome["result"]["reasoning"] == "noisy"


# ---------------------------------------------------------------------------
# 2. Timeout
# ---------------------------------------------------------------------------
def test_timeout_returns_controlled_failure(monkeypatch, assist_env):
    class HungProcess:
        pass

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 120))

    monkeypatch.setattr(ai_client.subprocess, "run", fake_run)
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["result"] is None
    assert outcome["error"] == "AI_TIMEOUT"
    assert "timeout" in outcome["details"].lower()


# ---------------------------------------------------------------------------
# 3. Invalid JSON on stdout
# ---------------------------------------------------------------------------
def test_invalid_json_stdout_returns_controlled_failure(monkeypatch, assist_env):
    class BadCompleted:
        returncode = 0
        stdout = b'{"ok": true, "result": {'   # truncated garbage
        stderr = b""

    monkeypatch.setattr(ai_client.subprocess, "run", lambda *a, **k: BadCompleted())
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_INVALID_RESPONSE"


def test_stdout_with_logs_mixed_in_returns_invalid_response(monkeypatch, assist_env):
    """stdout that is not pure JSON (e.g. print() logs) is rejected, not parsed."""
    class MessyCompleted:
        returncode = 0
        stdout = b"INFO: started\n" + json.dumps({"ok": True, "result": {}}).encode()
        stderr = b""

    monkeypatch.setattr(ai_client.subprocess, "run", lambda *a, **k: MessyCompleted())
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_INVALID_RESPONSE"


def test_envelope_shape_mismatch_rejected(monkeypatch, assist_env):
    class WrongEnvelope:
        returncode = 0
        stdout = json.dumps({"ok": False, "error": "boom"}).encode()
        stderr = b""

    monkeypatch.setattr(ai_client.subprocess, "run", lambda *a, **k: WrongEnvelope())
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_INVALID_RESPONSE"


# ---------------------------------------------------------------------------
# 4. Non-zero exit
# ---------------------------------------------------------------------------
def test_nonzero_exit_returns_controlled_failure(monkeypatch, assist_env):
    class CrashedCompleted:
        returncode = 3
        stdout = b""
        stderr = b"AI import failed:\nModuleNotFoundError: chroma_db missing"

    monkeypatch.setattr(ai_client.subprocess, "run", lambda *a, **k: CrashedCompleted())
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_EXIT_3"
    assert "ModuleNotFoundError" in outcome["details"]


def test_nonzero_exit_without_stderr_still_controlled(monkeypatch, assist_env):
    class SilentCrash:
        returncode = 1
        stdout = b""
        stderr = b""

    monkeypatch.setattr(ai_client.subprocess, "run", lambda *a, **k: SilentCrash())
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_EXIT_1"


# ---------------------------------------------------------------------------
# 5. AI disabled mode
# ---------------------------------------------------------------------------
def test_mode_off_never_invokes_subprocess(monkeypatch):
    monkeypatch.setenv("WASTE_AI_MODE", "off")
    monkeypatch.setenv("WASTE_AI_SRC", "C:/definitely/not/a/real/path")

    def boom(*a, **k):  # must never be reached
        raise AssertionError("subprocess.run called while AI_MODE=off")

    monkeypatch.setattr(ai_client.subprocess, "run", boom)
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_DISABLED"
    assert outcome["result"] is None


def test_invalid_mode_value_fails_safe_to_off(monkeypatch):
    monkeypatch.setenv("WASTE_AI_MODE", "production")   # not an allowed value
    assert ai_client.get_mode() == "off"


# ---------------------------------------------------------------------------
# Configuration guards
# ---------------------------------------------------------------------------
def test_missing_ai_src_configuration(monkeypatch):
    monkeypatch.setenv("WASTE_AI_MODE", "assist")
    monkeypatch.delenv("WASTE_AI_SRC", raising=False)
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_SOURCE_NOT_CONFIGURED"


def test_nonexistent_ai_src_path(monkeypatch):
    monkeypatch.setenv("WASTE_AI_MODE", "assist")
    monkeypatch.setenv("WASTE_AI_SRC", str(Path(BACKEND_DIR) / "definitely-missing-dir"))
    outcome = ai_client.analyze_waste_image(b"img")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_SOURCE_NOT_FOUND"


def test_timeout_config_falls_back_on_junk(monkeypatch):
    monkeypatch.setenv("WASTE_AI_TIMEOUT_S", "not-a-number")
    assert ai_client.get_timeout_s() == 120
    monkeypatch.setenv("WASTE_AI_TIMEOUT_S", "-5")
    assert ai_client.get_timeout_s() == 120
    monkeypatch.setenv("WASTE_AI_TIMEOUT_S", "30")
    assert ai_client.get_timeout_s() == 30


# ---------------------------------------------------------------------------
# 7. Latency is returned
# ---------------------------------------------------------------------------
def test_latency_measured_on_success_and_failure(monkeypatch, assist_env):
    outcome = ai_client.analyze_waste_image(b"img")
    assert isinstance(outcome["latency_ms"], int) and outcome["latency_ms"] >= 0

    class Crashed:
        returncode = 2
        stdout = b""
        stderr = b""

    monkeypatch.setattr(ai_client.subprocess, "run", lambda *a, **k: Crashed())
    failed = ai_client.analyze_waste_image(b"img")
    assert isinstance(failed["latency_ms"], int)


# ---------------------------------------------------------------------------
# 8/9. AI result preserved exactly — no vocabulary remapping, no fabrication
# ---------------------------------------------------------------------------
def test_ai_vocabulary_and_fields_preserved_verbatim(assist_env):
    outcome = ai_client.analyze_waste_image(b"img", prior_reports_at_location=0)
    result = outcome["result"]
    # every AI field survives untouched
    for field in (
        "image_usable", "unusable_reason", "waste_type", "waste_type_confidence",
        "severity", "severity_confidence", "reasoning", "follow_up_question",
        "recurring_flag", "prior_reports_at_location", "escalate_to_authority",
        "needs_human_review", "review_reasons", "disposal_guidance", "errors",
    ):
        assert field in result, f"AI field {field} lost in transport"
    # no legacy vocabulary invented
    assert "intervention_required" not in result
    assert "waste_type_pred" not in result
    # adapter does not fabricate provenance
    assert "model_name" not in result and "model_version" not in result


def test_verify_cleanup_round_trip(assist_env):
    outcome = ai_client.verify_cleanup(b"before-bytes", b"after-bytes",
                                       before_mime="image/jpeg", after_mime="image/png")
    assert outcome["success"] is True
    result = outcome["result"]
    assert result["after_image_usable"] is True
    assert result["cleanup_appears_complete"] is True
    assert result["confidence"] == 0.88
    assert result["admin_review_recommended"] is False
    assert result["_before_len"] == len(b"before-bytes")
    assert result["_after_len"] == len(b"after-bytes")


def test_verify_cleanup_disabled_mode(monkeypatch):
    monkeypatch.setenv("WASTE_AI_MODE", "off")
    outcome = ai_client.verify_cleanup(b"a", b"b")
    assert outcome["success"] is False
    assert outcome["error"] == "AI_DISABLED"
