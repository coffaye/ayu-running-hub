# Native Agent Format Retry Audit

## Scope

Branch: `native-agent-format-retry`.

This change adds one bounded retry per Native Agent stage for one failure only:
the provider completed successfully, but the non-empty response contains neither
an HTML root marker nor an HTML closing marker. The retry reuses the exact same
request and model configuration and adds no correction prompt. Pass 1 and Pass 2
are each limited to two attempts, so the complete runtime is limited to four
provider calls.

Empty output, provider balance/rate/transient failures, timeouts, incomplete
responses, content filtering, envelope/HTML validation, safety, language, PNG,
and Golden failures are not retried. A failed malformed response is never sent
to the draft sink and Pass 2 remains the only final source.

## Verification

- Targeted format-retry tests: 85 passed.
- Hub full pytest before closeout: 215 passed, 47 subtests passed.
- Three independent live runs using `deepseek-flash` / `high` / `65536` / `300s`
  all passed the unchanged Golden, load, language, safety, complete-HTML and PNG
  checks. Each used one successful attempt in Pass 1 and Pass 2; no live retry
  was needed.
- The production-entry staging run used the unchanged 9/13 input and generated
  the report through `scripts/generate_report.py`. Its manifest engine commit
  matched the pre-commit HEAD, and the report passed the strict HTML and
  self-contained safety validation. A real browser downloaded and rendered its
  PNG successfully.

No Native Skill, reference, snapshot, prompt, model setting, input fixture,
COROS collector, Worker, workflow, manifest in a tracked production checkout,
running_page checkout, or production report was changed. No main merge or
production deployment was performed.
