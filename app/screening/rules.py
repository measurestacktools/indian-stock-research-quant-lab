from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd

@dataclass
class Rule:
    name: str
    field: str
    op: str  # gt, lt, gte, lte, eq, not_null
    threshold: Optional[float]
    description: str

DEFAULT_RULES = [
    Rule("min_liquidity","avg_volume","gte",100000,"Minimum avg volume 100k"),
    Rule("max_de","debt_equity","lte",1.0,"Max D/E 1.0"),
    Rule("min_roe","roe","gte",12,"Min ROE 12%"),
    Rule("max_pe","pe","lte",40,"Max PE 40"),
    Rule("min_momentum","ret_63d","gte",0.02,"Min 63d return 2%"),
]

def eval_rule(rule: Rule, context: dict):
    val = context.get(rule.field)
    if val is None:
        return "UNKNOWN", f"{rule.name}: insufficient data for {rule.field}"
    try:
        if rule.op=="gt": passed = val > rule.threshold
        elif rule.op=="gte": passed = val >= rule.threshold
        elif rule.op=="lt": passed = val < rule.threshold
        elif rule.op=="lte": passed = val <= rule.threshold
        elif rule.op=="eq": passed = val == rule.threshold
        elif rule.op=="not_null": passed = val is not None
        else: passed=False
    except: return "UNKNOWN", f"{rule.name}: error evaluating"
    status = "PASSED" if passed else "FAILED"
    return status, f"{status}: {rule.description} (value {val:.3f} vs {rule.threshold})"

def evaluate_rules(context: dict, rules=None):
    if rules is None: rules=DEFAULT_RULES
    results=[]
    for r in rules: 
        status, msg = eval_rule(r, context)
        results.append({"rule":r.name,"status":status,"message":msg})
    return results
