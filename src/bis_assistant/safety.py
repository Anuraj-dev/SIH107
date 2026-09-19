"""Safety: never-infer list, refusal, disclaimers. Runs before any answer is returned."""
from __future__ import annotations
import re

DISCLAIMER_EN = ("Informational only — not a BIS ruling. Confirm IS number, year, QCO status and "
                 "testing with BIS / a BIS-recognised lab before manufacture or sale.")
DISCLAIMER_HI = ("Keval jankari hetu — BIS nirnay nahin. Utpadan/bikri se pehle IS number, varsh, QCO "
                 "sthiti aur parikshan BIS / manyata-prapt lab se pusht karen.")

BIS_CARE = "https://www.bis.gov.in | BIS Care app | Verify HUID / licences on manakonline.in"

# User asks for something we must never provide (EN + HI + Hinglish).
NEVER_PATTERNS = [
    (r"is (my|this) product (certified|compliant|approved)", "cert_claim"),
    (r"\bis (?:my|this|the) .{0,50}?\b(certified|compliant|approved)\b", "cert_claim"),
    (r"(confirm|declare|certify).{0,60}(certified|compliant|approved)", "cert_claim"),
    (r"(product|bottle|flask|bulb|उत्पाद|प्रोडक्ट).{0,40}\bis (certified|compliant|approved)\b",
     "cert_claim"),
    (r"(product|bottle|flask|bulb).{0,40}\bbis[\s-]*(certified|compliant|approved)\b",
     "cert_claim"),
    (r"(tell me if|let me know if).{0,80}\b(certified|compliant|approved|approval)\b",
     "cert_claim"),
    (r"does (this|it|my|the) .{0,40}have .{0,25}\b(bis )?(approval|licen[cs]e|certificate|certified)\b",
     "cert_claim"),
    (r"(मेरा|मेरी|यह|ये).{0,30}(उत्पाद|प्रोडक्ट|product).{0,40}"
     r"(certified|compliant|approved|प्रमाणित|सर्टिफाइड)", "cert_claim"),
    (r"क्या.{0,60}(certified|compliant|approved|प्रमाणित|सर्टिफाइड)", "cert_claim"),
    (r"\bkya\b.{0,60}(certified|compliant|approved|pramanit|sertified)", "cert_claim"),
    (r"(उत्पाद|प्रोडक्ट).{0,40}(certified|compliant|approved|प्रमाणित)", "cert_claim"),
    (r"will (my|this|the) .{0,50}?\b(licen[cs]e|approval|certified|approved)\b",
     "licence_guarantee"),
    (r"(guarantee|assure|vada|वादा|गारंटी).{0,50}"
     r"(licen[cs]e|approval|certificate|लाइसेंस)", "licence_guarantee"),
    (r"(licen[cs]e|लाइसेंस).{0,50}(guarantee|assure|vada|वादा|गारंटी)", "licence_guarantee"),
    (r"licen[cs]e ki guarantee", "licence_guarantee"),
    (r"give (me )?(the )?(full|complete|verbatim|exact) (text|clause|wording)", "full_text"),
    (r"(full|complete|entire|verbatim)\W+(?:\w+\W+){0,3}(texts?|clauses?|wording|standard)",
     "full_text"),
    (r"(पूर्ण|पूरा|पूरी).{0,30}(पाठ|मानक|text|clause|wording)", "full_text"),
    (r"(wording|text|quote).{0,25}clause\s*\d", "clause_verbatim"),
    (r"clause\s*\d+(\.\d+)*\s*(says|text|wording|quote)", "clause_verbatim"),
    (r"(पूरा|पूर्ण).{0,20}clause", "clause_verbatim"),
    (r"\b(?:invent|make up|fabricate|conjure)\b.{0,80}\b(?:standard\s+)?clause\b",
     "fabricated_clause"),
    (r"(predict|tell).*(test result|lab result|will (pass|fail))", "lab_result"),
    (r"(invent|make up|fabricate|conjure).*(standard|is number|clause)", "full_text"),
    (r"\b(?:legally(?:\s+binding)?|binding\s+legal|sue|liabilit\w*)\b", "legal_binding"),
    (r"(how long|timeline).*(guarantee|exactly|promise)", "timeline_guarantee"),
]


def check_never_infer(query: str) -> str | None:
    q = re.sub(r"\s+", " ", (query or "").lower())
    for pat, kind in NEVER_PATTERNS:
        if re.search(pat, q):
            return kind
    return None


REFUSAL_EN = {
    "cert_claim": "I can't declare any product certified/compliant — that needs BIS inspection + lab testing. I can list candidate standards and next steps.",
    "licence_guarantee": "I can't guarantee licence approval or timelines. I can explain the process, fee and testing steps from BIS pages.",
    "full_text": "I can't reproduce full paid standard text (copyright). I can share number/title/scope from Know-Your-Standard and link to the BIS e-sale.",
    "clause_verbatim": "I can't quote clause wording beyond what the authorised BIS page shows. See the citation link for the official text.",
    "fabricated_clause": "I can't invent a BIS clause or present made-up requirements as official. I can help find the relevant standard and cite its BIS source.",
    "lab_result": "I can't predict or invent lab results/accreditation. Confirm IS-wise scope on LIMS before sending samples.",
    "legal_binding": "I can't give binding legal advice. Confirm QCO/compulsion status with BIS or legal counsel.",
    "timeline_guarantee": "I can't promise exact timelines. I can share the standard process stages.",
}

REFUSAL_HI = {
    "cert_claim": "Main kisi utpad ko certified/compliant ghoshit nahin kar sakta — iske liye BIS nirikshan + lab parikshan chahiye. Ummeedvar manak aur agle kadam bata sakta hun.",
    "licence_guarantee": "Licence swikriti/samay ki guarantee nahin de sakta. Prakriya aur parikshan samjha sakta hun.",
    "full_text": "Poora paid manak text nahin de sakta (copyright). Number/title/scope aur BIS e-sale link de sakta hun.",
    "clause_verbatim": "Adhikrit BIS page se bahar clause shabd nahin de sakta. Aadhikarik path ke liye citation link dekhen.",
    "fabricated_clause": "Main BIS clause gadh nahin sakta ya banaye gaye niyamon ko aadhikarik nahin bata sakta. Main sambandhit manak aur BIS srot dhoondhne mein madad kar sakta hun.",
    "lab_result": "Lab parinam ka anumaan nahin laga sakta. LIMS par scope pusht karen.",
    "legal_binding": "Badhyakari kanuni salah nahin de sakta. BIS/vakeel se pusht karen.",
    "timeline_guarantee": "Nishchit samay-seema ka vada nahin kar sakta. Prakriya ke charan bata sakta hun.",
}
