def generate_report(symbol, price, affordable, liquidity, fundamentals, features, ai_analysis, critic, rule_results, backtest, data_quality):
    lines=[f"# Research Report: {symbol}", f"Reference price: ₹{price:.2f}", f"Affordable with current budget? {'YES' if affordable else 'NO'}", f"Liquidity: {liquidity}", "", "## Business Summary", ai_analysis.get("business_summary","Data unavailable") if ai_analysis else "AI unavailable", "## Growth", str(fundamentals), "## Risk", str(critic.get('overall_assessment','') if critic else 'N/A'), "## Rule Results"]
    for r in (rule_results or []): lines.append(f"- {r['message']}")
    lines += ["", "## Backtest", str(backtest.get('metrics',{}) if backtest else 'N/A'), "## Data Quality", str(data_quality), "## Missing Data", str(ai_analysis.get('missing_information',[]) if ai_analysis else []), "", "> Research candidate — not an automatic trade instruction."]
    return "\n".join(lines)
