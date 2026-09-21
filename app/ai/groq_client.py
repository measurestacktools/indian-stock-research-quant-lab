import os, json, hashlib, logging, datetime
from app.config.settings import settings
from app.utils.cache import get_cache, set_cache, cache_key
from app.ai.schemas import AnalystOutput, CriticOutput, contains_banned

logger=logging.getLogger(__name__)

SYSTEM_ANALYST = "You are a disciplined equity analyst. Use ONLY verified data provided. Never invent prices, financials, news, or dates. If info unavailable say so. Output valid JSON per schema. Confidence is about analysis quality, not future price. Never say guaranteed return/certain winner/will definitely rise."
SYSTEM_CRITIC = "You are a devil's advocate. Attack the thesis with evidence. Identify overinterpreted metrics, failure modes, valuation concerns, data gaps. Be constructive not contrarian for its own sake. JSON only."

def _mock_analyst(symbol, data):
    return AnalystOutput(business_summary=f"{symbol} business summary from verified data (mock).", fundamental_interpretation="Trends based on provided metrics; limited history flagged.", positive_factors=["Positive momentum where observed"], risk_factors=["Volatility","Limited fundamental coverage"], contradictions=[], missing_information=["Full cashflow not available"], thesis="Candidate for research, not trade instruction.", thesis_invalidators=["Earnings reversal","Regime change"], confidence="low").model_dump()

def _mock_critic(thesis):
    return CriticOutput(strongest_counter_argument="Momentum may be mean-reverting; sample insufficient.", overinterpreted_metrics=["3m momentum"], failure_modes=["Drawdown if trend breaks"], valuation_concern="PE may be elevated vs growth if fundamentals stale.", data_quality_concerns=["Fundamentals may be delayed"], missing_information=["Management commentary"], overall_assessment="Needs more evidence before conviction.").model_dump()

def analyst_call(symbol: str, verified_data: dict, force_mock=False):
    ck = cache_key("analyst", symbol, hashlib.sha256(json.dumps(verified_data, sort_keys=True, default=str).encode()).hexdigest())
    cached = get_cache(ck, ttl_seconds=7*86400)
    if cached: return cached
    api_key = os.getenv("GROQ_API_KEY") or settings.groq_api_key
    if force_mock or not api_key:
        out=_mock_analyst(symbol, verified_data)
        set_cache(ck, out); return out
    try:
        from groq import Groq
        client=Groq(api_key=api_key)
        prompt = f"Symbol {symbol}\nVerified data: {json.dumps(verified_data, default=str)[:6000]}\nReturn JSON with keys business_summary,fundamental_interpretation,positive_factors,risk_factors,contradictions,missing_information,thesis,thesis_invalidators,confidence"
        resp = client.chat.completions.create(model=settings.groq_model, messages=[{"role":"system","content":SYSTEM_ANALYST},{"role":"user","content":prompt}], response_format={"type":"json_object"}, temperature=0.2)
        txt = resp.choices[0].message.content
        data=json.loads(txt)
        # validate & ban check
        obj=AnalystOutput(**data)
        if contains_banned(obj.thesis) or contains_banned(obj.business_summary): raise ValueError("Banned phrase detected")
        out=obj.model_dump(); set_cache(ck, out); return out
    except Exception as e:
        logger.warning(f"Groq analyst failed {e}, using mock")
        out=_mock_analyst(symbol, verified_data); set_cache(ck, out); return out

def critic_call(symbol: str, analyst_output: dict, verified_data: dict, force_mock=False):
    ck = cache_key("critic", symbol, hashlib.sha256(json.dumps(analyst_output, sort_keys=True).encode()).hexdigest())
    cached=get_cache(ck, ttl_seconds=7*86400)
    if cached: return cached
    api_key = os.getenv("GROQ_API_KEY") or settings.groq_api_key
    if force_mock or not api_key:
        out=_mock_critic(analyst_output); set_cache(ck,out); return out
    try:
        from groq import Groq
        client=Groq(api_key=api_key)
        prompt = f"Symbol {symbol}\nAnalyst thesis: {json.dumps(analyst_output)[:4000]}\nVerified data: {json.dumps(verified_data, default=str)[:4000]}\nReturn JSON critic."
        resp = client.chat.completions.create(model=settings.groq_model, messages=[{"role":"system","content":SYSTEM_CRITIC},{"role":"user","content":prompt}], response_format={"type":"json_object"}, temperature=0.2)
        data=json.loads(resp.choices[0].message.content)
        obj=CriticOutput(**data)
        out=obj.model_dump(); set_cache(ck,out); return out
    except Exception as e:
        logger.warning(f"Groq critic failed {e}, mock")
        out=_mock_critic(analyst_output); set_cache(ck,out); return out

def contradiction_check(analyst: dict, critic: dict):
    # deterministic: if analyst missing info overlaps critic concerns, flag
    overlap = set(analyst.get("missing_information",[])).intersection(set(critic.get("missing_information",[])))
    return {"overlap_missing": list(overlap), "has_contradiction": len(analyst.get("contradictions",[]))>0}
