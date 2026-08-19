# Python 3.11 | solver/ai.py
# Purpose: Cerebras Cloud AI integration for smart decision making and automated analysis

import os
import logging

logger = logging.getLogger(__name__)

CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "csk-tfpn586tr2k65rtwrjm656e49y45j2jvkhfrkwe2vr382eme")

def get_cerebras_client():
    try:
        from cerebras.cloud.sdk import Cerebras
        return Cerebras(api_key=CEREBRAS_API_KEY)
    except Exception as e:
        logger.warning(f"Could not initialize Cerebras client: {e}")
        return None

def analyze_status(prompt: str) -> str:
    """
    Sends prompt to Cerebras AI (Gemma/Llama) and returns analysis string.
    """
    client = get_cerebras_client()
    if not client:
        return ""
    try:
        resp = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are an expert web automation analyzer."},
                {"role": "user", "content": prompt}
            ],
            model="llama3.1-8b",
            max_completion_tokens=500,
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning(f"Cerebras query failed: {e}")
        return ""
