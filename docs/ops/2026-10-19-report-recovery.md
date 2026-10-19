# 2026-10-19 report recovery

The production report request failed before model generation with collector
HTTP 503 / `COROS_REAUTH_REQUIRED`. A fresh, dedicated browser-authorized
COROS grant restored the existing broker to READY (credential generation 4).
The read-only diagnostic then returned HTTP 200 for the requested activity
date, 2026-10-18. The temporary bootstrap secret and local authorization
cache were removed. No interactive client's credentials were reused.

The first report retry progressed through the model calls but failed closed
at Pass 2 with `unsafe_external_resource`, `dynamic-resource`,
`resource_creation`. Its HTML was not installed or published. Safe logs do
not retain the rejected model body, so this metadata does not establish which
resource element or variable caused the match.

The request instructions now describe the already-enforced self-contained
contract explicitly, including direct Canvas PNG drawing and a local download
anchor. Validation rules have not been relaxed, no HTML repair or unsafe-output
fallback was introduced, and no extra model-call or safety-retry path was added.
The model configuration, two-pass design, Native Skill snapshot, input adapter,
collector, and training facts remain unchanged.

Separately, failed status records now recheck the original GitHub workflow so
operator reruns cannot remain permanently displayed as the initial failure.
This status read does not dispatch generation and fails closed on API errors.

Checks: Hub full pytest 216 passed / 47 subtests passed, Worker 27 passed,
Worker typecheck, Python compileall, unchanged Native Skill snapshot validation,
and diff whitespace checks. Production generation is validated via the normal
generate/publish/Pages workflow, not by substituting a local report file.
