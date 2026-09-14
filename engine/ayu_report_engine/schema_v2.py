"""Candidate-only JSON Schema for Report Intelligence v2.

The legacy StructuredReport schema remains the active production contract.  This
module is intentionally separate so a candidate insight contract cannot switch
the production generation path by importing a new version constant.
"""

from __future__ import annotations

from typing import Any


REPORT_INTELLIGENCE_CONTRACT_VERSION = "1.2-candidate"
STRUCTURED_INSIGHT_SCHEMA_VERSION = "structured-insight-v1"
STRUCTURED_INSIGHT_SCHEMA_NAME = "ayu_structured_insight_candidate"
INSIGHT_CATEGORIES = (
    "execution",
    "output",
    "cost",
    "load",
    "recovery",
    "context",
    "uncertainty",
)


def structured_insight_json_schema() -> dict[str, Any]:
    """Return the candidate StructuredInsight schema without changing v1.1."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ayu-running.example/schemas/structured-insight-1.2-candidate.json",
        "title": "Ayu StructuredInsight candidate",
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "category", "interpretation", "evidenceRefs", "confidence", "uncertainty"],
        "properties": {
            "id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]{0,63}$"},
            "category": {"type": "string", "enum": list(INSIGHT_CATEGORIES)},
            "interpretation": {"type": "string", "minLength": 1},
            "evidenceRefs": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "confidence": {"type": ["string", "null"]},
            "uncertainty": {"type": ["string", "null"]},
        },
        "allOf": [
            {
                "if": {"properties": {"category": {"const": "uncertainty"}}},
                "then": {"properties": {"evidenceRefs": {"minItems": 0}}},
                "else": {"properties": {"evidenceRefs": {"minItems": 1}}},
            }
        ],
    }


def structured_insight_bundle_json_schema() -> dict[str, Any]:
    """Return the deterministic candidate fixture/bundle schema."""

    insight = structured_insight_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ayu-running.example/schemas/report-intelligence-v2-candidate.json",
        "title": "Ayu Report Intelligence v2 candidate output",
        "type": "object",
        "additionalProperties": False,
        "required": ["contractVersion", "structuredInsightVersion", "insights"],
        "properties": {
            "contractVersion": {"const": REPORT_INTELLIGENCE_CONTRACT_VERSION},
            "evidencePackVersion": {"const": "run-evidence-pack-v1"},
            "structuredInsightVersion": {"const": STRUCTURED_INSIGHT_SCHEMA_VERSION},
            "insights": {"type": "array", "items": insight, "maxItems": 32},
        },
    }
