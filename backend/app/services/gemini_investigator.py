"""
ReconAI - Google Gemini AI Investigation Provider.

Interacts with the Google Gemini API to investigate reconciliation exceptions.
Uses structured output, strict prompt guardrails, and safe error handling.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from app.services.ai_investigator import AIInvestigator
from app.services.investigation_models import (
    EvidencePackage,
    InvestigationClassification,
    InvestigationResult,
    RecommendedAction,
)

INVESTIGATION_PROMPT_TEMPLATE = """You are ReconAI's Expert Financial Reconciliation Investigator.
Your task is to investigate an unresolved financial reconciliation exception based ONLY on the provided evidence.

CRITICAL FINANCIAL INTEGRITY RULES:
1. Use ONLY observed facts provided in the evidence package.
2. DO NOT invent transactions, bank fees, timestamps, IDs, or contractual terms.
3. No explicit fee field exists in the data model. If payment > settlement, you may infer that it is consistent with a fee, but you MUST state that no fee schedule is recorded.
4. Distinguish clearly between OBSERVED FACTS, INFERENCES, and UNCERTAINTIES.
5. If evidence is insufficient, explicitly classify as INSUFFICIENT_EVIDENCE or AMBIGUOUS.
6. Provide output strictly conforming to the requested JSON schema.

EVIDENCE PACKAGE:
{evidence_json}
"""


class GeminiInvestigator(AIInvestigator):
    """Concrete AI Investigator powered by Google Gemini."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model

    def investigate(self, evidence: EvidencePackage) -> InvestigationResult:
        if not self.api_key:
            return InvestigationResult(
                case_id=evidence.case_id,
                classification=InvestigationClassification.INSUFFICIENT_EVIDENCE,
                summary="Gemini API key not configured.",
                observed_facts=["API key missing from environment"],
                inferences=[],
                uncertainties=["Unable to contact Gemini provider"],
                recommended_action=RecommendedAction.FLAG_FOR_MANUAL_REVIEW,
                needs_human_review=True,
                investigator_model=f"{self.model}-disabled",
            )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            prompt = INVESTIGATION_PROMPT_TEMPLATE.format(
                evidence_json=json.dumps(evidence.__dict__, default=str, indent=2)
            )

            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=InvestigationResult,
                    temperature=0.1,
                ),
            )

            data = json.loads(response.text)
            return InvestigationResult(
                case_id=evidence.case_id,
                classification=InvestigationClassification(data["classification"]),
                summary=data["summary"],
                observed_facts=data.get("observed_facts", []),
                inferences=data.get("inferences", []),
                uncertainties=data.get("uncertainties", []),
                recommended_action=RecommendedAction(data["recommended_action"]),
                needs_human_review=data.get("needs_human_review", True),
                investigator_model=self.model,
            )
        except Exception as e:
            return InvestigationResult(
                case_id=evidence.case_id,
                classification=InvestigationClassification.INSUFFICIENT_EVIDENCE,
                summary=f"Gemini investigation failed due to error: {str(e)}",
                observed_facts=[],
                inferences=[],
                uncertainties=[f"Provider error: {str(e)}"],
                recommended_action=RecommendedAction.FLAG_FOR_MANUAL_REVIEW,
                needs_human_review=True,
                investigator_model=f"{self.model}-fallback",
            )