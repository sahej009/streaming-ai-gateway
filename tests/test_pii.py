from app.connectors.base import redact_pii

sample_text = "My name is John Doe and my email is john.doe@acmecorp.com. Call me at 555-019-8372."
print("Original:", sample_text)

safe_text = redact_pii(sample_text)
print("Redacted:", safe_text)