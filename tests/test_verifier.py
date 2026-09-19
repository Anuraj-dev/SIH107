"""Citation verifier: English 'is 1' is not IS 1."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bis_assistant.verifier import IS_RE, verify  # noqa: E402


def test_is_1_litre_not_an_is_number():
    text = "Capacity is 1 litre vacuum flask. **IS 17803:2022**"
    assert "1" not in IS_RE.findall(text)
    assert "17803" in IS_RE.findall(text)
    viols = verify({
        "text": text,
        "citations": ["IS 17803:2022 — flask — Source: https://www.bis.gov.in/x"],
        "refused": False,
        "kind": "answered",
    })
    assert viols == []
