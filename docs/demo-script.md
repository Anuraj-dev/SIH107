# SIH demo script (7 min)
1. **Problem** (30s): MSMEs can't find which IS applies — show fragmented BIS portals.
2. **Vague query** (90s): type "steel bottle" → assistant ASKS (type + capacity) instead of
   guessing. Pick a chip → gets IS 17803:2022 + scheme + citation + disclaimer.
3. **Hindi** (60s): "नल के पानी का मानक?" → IS 10500 in Hindi.
4. **Safety** (60s): "Guarantee my licence" → hard refusal; "full text" → copyright refusal.
5. **HUID/CRS** (60s): hallmarking journey + LED/CRS flow.
6. **Trust layer** (60s): eval 267/267, verifier trips 0, red-team 44/44, erasure demo
   (`DELETE /me`), metrics endpoint.
7. **Close** (30s): allowlisted sources only, versioned KB with review queue.

Fallbacks: API down → CLI `PYTHONPATH=src python -m bis_assistant.cli`; UI down → curl `/chat`.
