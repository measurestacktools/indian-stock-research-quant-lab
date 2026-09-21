from app.ai.groq_client import analyst_call, critic_call
import json
print(json.dumps(analyst_call("RELIANCE", {"price":1000}, force_mock=True), indent=2))
