from app.security.redaction import redact


def test_secrets_and_base64_are_redacted() -> None:
    value = 'Authorization: Bearer abc.secret-123 api_key="my-key" data:image/png;base64,AAAA'
    redacted = redact(value)
    assert "abc.secret" not in redacted
    assert "my-key" not in redacted
    assert "AAAA" not in redacted

