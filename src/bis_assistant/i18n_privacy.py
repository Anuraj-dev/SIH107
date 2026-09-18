"""Minimal EN/HI i18n + PII handling (DPDP Act 2023: consent, minimisation, retention)."""
from __future__ import annotations
import re
from datetime import datetime, timedelta

STRINGS = {
    "ask_clarify_en": "To ground this I need 1–2 details:",
    "ask_clarify_hi": "Sahi manak ke liye 1–2 vivaran chahiye:",
    "candidates_en": "Candidate standards:",
    "candidates_hi": "Sambhavit manak:",
    "no_source_en": "I don't have an authorised BIS source for that — I won't guess. Try Know-Your-Standard or ask with product material/use.",
    "no_source_hi": "Iske liye mere paas adhikrit BIS srot nahin hai — andaza nahin lagaunga. Know-Your-Standard dekhen ya samagri/upayog sahit poochhen.",
    "consent_en": "Storing business contact details only with your explicit 'I consent'. Say 'delete my data' anytime to erase. Test reports are session-only.",
    "consent_hi": "Vyavsayik sampark vivaran keval aapki spasht 'sahmati' par rakha jayega. 'Mera data hatayen' kahne par turant mitaya jayega.",
}

PII_PATTERNS = {
    "phone": re.compile(r"(?:\+?91[\s-]?)?[6-9](?:[\s-]?\d){9}"),
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "aadhaar_like": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
}


def detect_lang(text: str) -> str:
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    return "en"


def find_pii(text: str) -> dict:
    return {k: bool(p.search(text)) for k, p in PII_PATTERNS.items()}


def redact(text: str) -> str:
    for p in PII_PATTERNS.values():
        text = p.sub("[REDACTED]", text)
    return text


class ConsentStore:
    """In-memory demo store: consent flag, purpose, 90-day retention, delete-on-request."""

    def __init__(self):
        self.records: dict[str, dict] = {}

    def set_consent(self, user_id: str, consent: bool, purpose: str = "personalise BIS licensing guidance"):
        self.records[user_id] = {"consent": consent, "purpose": purpose,
                                 "stored_at": datetime.utcnow().isoformat(), "profile": {}}

    def save_profile(self, user_id: str, profile: dict) -> bool:
        rec = self.records.get(user_id)
        if not rec or not rec["consent"]:
            return False
        # minimisation: only business fields
        allowed = {"firm", "city", "product", "phone", "email"}
        rec["profile"] = {k: v for k, v in profile.items() if k in allowed}
        return True

    def delete(self, user_id: str):
        self.records.pop(user_id, None)

    def expired(self, user_id: str, days: int = 90) -> bool:
        rec = self.records.get(user_id)
        if not rec:
            return True
        stored = datetime.fromisoformat(rec["stored_at"])
        return datetime.utcnow() - stored > timedelta(days=days)
