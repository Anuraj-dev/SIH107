# Chatbot acceptance set, version 3

`groq-chatbot-50.json` is the fixed first-pass acceptance set for the live grounded chat flow. It has 50 varied prompts: 20 product and standard questions, 10 BIS scheme or service questions, 10 requests the assistant must refuse, 5 plain-language definitions, and 5 status/version checks. Questions include English and Hindi, specific standard numbers, missing details, available catalogue records, and requests outside the verified scope.

Each `expected_answer` describes the answer shape a reviewer should see. The structured fields are the automated checks: expected standard or scheme, refusal, and citation URL. The model may phrase a correct answer differently. A passing string match alone is not proof that the answer is safe; inspect the answer and its cited source when a case fails or changes.

This is a provider-backed acceptance set, not a deterministic offline baseline. Configure and export `BIS_LLM_PROVIDER`, `BIS_LLM_MODEL`, and `BIS_LLM_API_KEY` (plus the RAG corpus settings when needed), then run `BIS_EVAL_ALLOW_ENV=1 PYTHONPATH=src .venv/bin/python eval/run_groq_50.py`. That sends 50 prompts to the configured LLM; without a configured model, the app correctly returns its model-unavailable response and the answer-quality checks cannot run. Credential-free CI instead tests the LLM-only routing and offline contract with mocked generation. The report saves only case IDs, pass/fail checks, response kind, and model mode under `eval/results/`; it does not save prompts or answer text.

Fix one failing case at a time. Add a regression test or a narrow data/routing correction, rerun the case, then rerun all 50 before changing the baseline.
