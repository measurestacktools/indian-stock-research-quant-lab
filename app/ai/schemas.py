from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class AnalystOutput(BaseModel):
    business_summary: str
    fundamental_interpretation: str
    positive_factors: List[str]
    risk_factors: List[str]
    contradictions: List[str]
    missing_information: List[str]
    thesis: str
    thesis_invalidators: List[str]
    confidence: Literal["low","medium","high"]

class CriticOutput(BaseModel):
    strongest_counter_argument: str
    overinterpreted_metrics: List[str]
    failure_modes: List[str]
    valuation_concern: str
    data_quality_concerns: List[str]
    missing_information: List[str]
    overall_assessment: str

BANNED_PHRASES = ["guaranteed return","certain winner","will definitely rise","sure profit"]
def contains_banned(text: str) -> bool:
    low=text.lower()
    return any(p in low for p in BANNED_PHRASES)
