"""Safety: never-infer list, refusal, disclaimers. Runs before any answer is returned."""
from __future__ import annotations
import re

DISCLAIMER_EN = ("Informational only — not a BIS ruling. Confirm IS number, year, QCO status and "
                 "testing with BIS / a BIS-recognised lab before manufacture or sale.")
DISCLAIMER_HI = ("Keval jankari hetu — BIS nirnay nahin. Utpadan/bikri se pehle IS number, varsh, QCO "
                 "sthiti aur parikshan BIS / manyata-prapt lab se pusht karen.")

BIS_CARE = "https://www.bis.gov.in | BIS Care app | Verify HUID / licences on manakonline.in"

# User asks for something we must never provide
NEVER_PATTERNS = [
    (r"is (my|this) product (certified|compliant|approved)", "cert_claim"),
    (r"(guarantee|assure).*(licen[cs]e|approval|certificate)", "licence_guarantee"),
    (r"give (me )?(the )?(full|complete|verbatim|exact) (text|clause|wording)", "full_text"),
    (r"clause\s*\d+(\.\d+)*\s*(says|text|wording|quote)", "clause_verbatim"),
    (r"(predict|tell).*(test result|lab result|will (pass|fail))", "lab_result"),
    (r"(invent|make up|fabricate|conjure).*(standard|is number|clause)", "full_text"),
    (r"(legally|legally binding|binding legal|sue|liabilit)", "legal_binding"),
    (r"(how long|timeline).*(guarantee|exactly|promise)", "timeline_guarantee"),
]


def check_never_infer(query: str) -> str | None:
    q = query.lower()
    for pat, kind in NEVER_PATTERNS:
        if re.search(pat, q):
            return kind
    return None


REFUSAL_EN = {
    "cert_claim": "I can't declare any product certified/compliant — that needs BIS inspection + lab testing. I can list candidate standards and next steps.",
    "licence_guarantee": "I can't guarantee licence approval or timelines. I can explain the process, fee and testing steps from BIS pages.",
    "full_text": "I can't reproduce full paid standard text (copyright). I can share number/title/scope from Know-Your-Standard and link to the BIS e-sale.",
    "clause_verbatim": "I can't quote clause wording beyond what the authorised BIS page shows. See the citation link for the official text.",
    "lab_result": "I can't predict or invent lab results/accreditation. Confirm IS-wise scope on LIMS before sending samples.",
    "legal_binding": "I can't give binding legal advice. Confirm QCO/compulsion status with BIS or legal counsel.",
    "timeline_guarantee": "I can't promise exact timelines. I can share the standard process stages.",
}

REFUSAL_HI = {
    "cert_claim": "Main kisi utpad ko certified/compliant ghoshit nahin kar sakta — iske liye BIS nirikshan + lab parikshan chahiye. Ummeedvar manak aur agle kadam bata sakta hun.",
    "licence_guarantee": "Licence swikriti/samay ki guarantee nahin de sakta. Prakriya aur parikshan samjha sakta hun.",
    "full_text": "Poora paid manak text nahin de sakta (copyright). Number/title/scope aur BIS e-sale link de sakta hun.",
    "clause_verbatim": "Adhikrit BIS page se bahar clause shabd nahin de sakta. Aadhikarik path ke liye citation link dekhen.",
    "lab_result": "Lab parinam ka anumaan nahin laga sakta. LIMS par scope pusht karen.",
    "legal_binding": "Badhyakari kanuni salah nahin de sakta. BIS/vakeel se pusht karen.",
    "timeline_guarantee": "Nishchit samay-seema ka vada nahin kar sakta. Prakriya ke charan bata sakta hun.",
}
