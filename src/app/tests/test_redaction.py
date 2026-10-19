"""Nothing that leaves the machine's own state carries a credential.

Two boundaries were missing one, and both are now the same call:

* `harness._why` put a CLI's stderr into the job's error, and a CLI that refuses
  a key quotes the key back;
* `web/jobs` stored `traceback.format_exc()` in a column that
  `GET /api/jobs/{id}/log` serves to any allowed origin — the browser extension
  on any listing page among them.

The redactor itself had a hole worth pinning: `Authorization: Bearer sk-…` kept
the token, because the named-secret pattern matched as far as `Bearer` and the
pattern that knows the token's shape then found nothing left to match.
"""

from app.agentledger import redact
from app.web.jobs import _failure_line


def test_a_bearer_token_is_gone():
    assert "sk-abcdef123456" not in redact("Authorization: Bearer sk-abcdef123456")


def test_a_named_key_is_gone():
    assert "zzz" not in redact("api_key=zzz")
    assert "hunter2" not in redact("password: hunter2")
    assert "abc123" not in redact("x-api-key = abc123")


def test_a_bare_key_by_shape_is_gone():
    assert "sk-live-9999999999" not in redact("refused: sk-live-9999999999")


def test_ordinary_text_is_left_alone():
    """A redactor that eats the message is a redactor nobody keeps."""
    said = "the model exited 1: context length exceeded"
    assert redact(said) == said


def test_the_result_is_bounded():
    assert len(redact("x" * 5000)) == 1000
    assert len(redact("x" * 5000, limit=40)) == 40


def test_a_job_failure_line_names_the_place_not_the_traceback():
    try:
        raise ValueError("key sk-live-424242 was refused")
    except ValueError as exc:
        line = _failure_line(exc)

    assert "ValueError" in line
    assert "sk-live-424242" not in line
    assert "Traceback" not in line
    assert len(line) <= 500
