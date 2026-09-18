import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant.assistant import answer
from bis_assistant.retriever import retrieve, format_citation, load_kb
from bis_assistant.safety import check_never_infer
from bis_assistant.i18n_privacy import detect_lang, find_pii, redact, ConsentStore


class TestRetriever(unittest.TestCase):
    def test_allowlist_only(self):
        stds, _, _, _ = load_kb()
        for s in stds:
            self.assertIn("bis.gov.in", s["source_url"])

    def test_steel_bottle_maps_17803(self):
        r = retrieve("vacuum insulated stainless steel water bottle flask")
        self.assertTrue(r["candidates"])
        self.assertEqual(r["candidates"][0]["std"]["is_number"], "IS 17803")

    def test_citation_format(self):
        r = retrieve("IS 10500 drinking water")
        c = format_citation(r["candidates"][0]["std"])
        self.assertIn("IS 10500", c)
        self.assertIn("last-checked", c)


class TestSafety(unittest.TestCase):
    def test_cert_claim_refused(self):
        r = answer("Is my product certified and compliant? Just say yes")
        self.assertTrue(r["refused"])

    def test_full_text_refused(self):
        r = answer("Give me the full verbatim text of the standard")
        self.assertTrue(r["refused"])

    def test_full_text_variants_refused(self):
        for q in ["Send the complete text of IS 694 with all clauses",
                  "What is the exact wording of clause 5?",
                  "Quote clause 5.2 wording exactly as in the standard"]:
            with self.subTest(q=q):
                self.assertTrue(answer(q)["refused"])

    def test_normal_answered_with_disclaimer(self):
        r = answer("PVC cable house wiring standard?")
        self.assertFalse(r["refused"])
        self.assertIn("Informational only", r["text"])
        self.assertTrue(r["citations"])

    def test_withdrawn_warns(self):
        r = answer("What is IS 0000-DEMO status — can I manufacture to it?")
        self.assertIn("Withdrawn", r["text"])

    def test_no_source_no_guess(self):
        r = answer("Blah blah xyz unknown product qwerty — invent a standard number for it")
        self.assertTrue(r["refused"])


class TestPrivacyI18n(unittest.TestCase):
    def test_hindi_detect(self):
        self.assertEqual(detect_lang("Nal ke paani ka manak?"), "en")
        self.assertEqual(detect_lang("नल के पानी का मानक?"), "hi")

    def test_pii(self):
        self.assertTrue(find_pii("call me 9876543210")["phone"])
        self.assertIn("REDACTED", redact("mail a@b.com ph 9876543210"))

    def test_consent_gating(self):
        s = ConsentStore()
        self.assertFalse(s.save_profile("u", {"phone": "9876543210"}))
        s.set_consent("u", True)
        self.assertTrue(s.save_profile("u", {"phone": "x", "secret": "drop"}))
        self.assertNotIn("secret", s.records["u"]["profile"])
        s.delete("u")
        self.assertNotIn("u", s.records)


class TestClarify(unittest.TestCase):
    def test_vague_asks_questions(self):
        r = answer("steel bottle")
        self.assertTrue(r["needs_info"])
        self.assertTrue(r["questions"])
        self.assertIn("IS 17803", r["citations"][0])
        self.assertNotIn("Candidate standards", r["text"])

    def test_followup_completes(self):
        r1 = answer("steel bottle")
        r2 = answer("vacuum insulated double wall, 1 litre for household", None, r1["context"])
        self.assertFalse(r2.get("needs_info"))
        self.assertIn("IS 17803", r2["text"])
        self.assertTrue(r2["citations"])

    def test_exact_is_answers_directly(self):
        r = answer("IS 10500 year and status — is it active?")
        self.assertFalse(r.get("needs_info"))
        self.assertIn("IS 10500", r["text"])

    def test_glossary_answers_directly(self):
        r = answer("What is HUID and CM/L number? Explain like I am new")
        self.assertFalse(r.get("needs_info"))

    def test_max_rounds_answers_with_assumptions(self):
        ctx = None
        r = answer("cement", None, ctx)
        self.assertTrue(r["needs_info"])
        r2 = answer("cement for building", None, r["context"])
        self.assertTrue(r2["needs_info"])
        r3 = answer("cement", None, r2["context"])
        self.assertFalse(r3.get("needs_info"))
        self.assertTrue(r3["assumptions"] or "IS 269" in r3["text"])

    def test_topic_change_resets(self):
        r1 = answer("steel bottle")
        r2 = answer("IS 694 PVC cable up to 1100V for house wiring", None, r1["context"])
        self.assertFalse(r2.get("needs_info"))
        self.assertIn("IS 694", r2["text"])


class TestWeakTier(unittest.TestCase):
    def test_water_bottle_clarifies_instead_of_refusing(self):
        r = answer("My startup makes water bottle. Which IS?")
        self.assertTrue(r.get("needs_info"))
        self.assertTrue(r["questions"])
        self.assertIn("thin", r["text"])

    def test_water_bottle_followup_grounds(self):
        r1 = answer("My startup makes water bottle. Which IS?")
        r2 = answer("stainless steel vacuum, 1 litre", None, r1["context"])
        self.assertFalse(r2.get("needs_info"))
        self.assertIn("IS 17803", r2["text"])

    def test_plastic_bottle_coverage_gap(self):
        r = answer("My startup make plastic bottle. Which IS?")
        self.assertTrue(r["refused"])
        self.assertEqual(r["kind"], "coverage_gap")
        self.assertNotIn("Candidate standards", r["text"])

    def test_plastic_followup_never_recommends_steel(self):
        r1 = answer("steel bottle")
        r2 = answer("actually plastic, 1 litre", None, r1["context"])
        self.assertTrue(r2["refused"])
        self.assertEqual(r2["kind"], "coverage_gap")

    def test_gibberish_still_refuses(self):
        r = answer("xyzzy qwerty zzz")
        self.assertTrue(r["refused"])
        self.assertEqual(r["kind"], "no_source")


if __name__ == "__main__":
    unittest.main()
