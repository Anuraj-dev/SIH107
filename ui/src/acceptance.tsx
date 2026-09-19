import { useMemo, useState } from "react";
import cases from "../../eval/datasets/v3/groq-chatbot-50.json";
import "./styles.css";

type Case = (typeof cases)[number];

const categoryNames: Record<string, string> = {
  product: "Products & standards",
  scheme: "BIS schemes & services",
  adversarial: "Safety & refusal",
  glossary: "Definitions",
  versioning: "Status & editions",
};

export default function AcceptancePanel({ onAsk, disabled }: {
  onAsk: (item: Case) => void;
  disabled: boolean;
}) {
  const [difficulty, setDifficulty] = useState<"challenging" | "all">("challenging");
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const challengingCount = cases.filter((item) => item.difficulty === "challenging").length;

  const visible = useMemo(() => cases.filter((item) => {
    const matchDifficulty = difficulty === "all" || item.difficulty === "challenging";
    const matchCategory = category === "all" || item.category === category;
    const needle = search.trim().toLowerCase();
    const matchSearch = !needle || `${item.id} ${item.query} ${item.expected_answer}`
      .toLowerCase().includes(needle);
    return matchDifficulty && matchCategory && matchSearch;
  }), [difficulty, category, search]);

  return (
    <section className="wrap acceptance" aria-labelledby="acceptance-title">
      <div className="acceptance-head">
        <div>
          <p className="eyebrow">FIXED ACCEPTANCE SET · V3</p>
          <h1 id="acceptance-title">Challenge the assistant</h1>
          <p className="acceptance-intro">
            Review the exact prompts and expected answer shape. Start with edge cases;
            each prompt opens in the live chat with its sources visible.
          </p>
        </div>
        <div className="acceptance-count" aria-label={`${cases.length} questions, ${challengingCount} challenging`}>
          <strong>{cases.length}</strong><span>fixed questions</span>
          <small>{challengingCount} challenging</small>
        </div>
      </div>

      <div className="acceptance-toolbar">
        <div className="bench-switch" role="group" aria-label="Question difficulty">
          <button type="button" className={difficulty === "challenging" ? "selected" : ""}
            aria-pressed={difficulty === "challenging"}
            onClick={() => setDifficulty("challenging")}>
            Challenge set <span>{challengingCount}</span>
          </button>
          <button type="button" className={difficulty === "all" ? "selected" : ""}
            aria-pressed={difficulty === "all"} onClick={() => setDifficulty("all")}>
            All questions <span>{cases.length}</span>
          </button>
        </div>
        <label className="sr-only" htmlFor="case-category">Filter by topic</label>
        <select id="case-category" className="case-select" value={category}
          onChange={(event) => setCategory(event.target.value)}>
          <option value="all">All topics</option>
          {Object.entries(categoryNames).map(([key, label]) =>
            <option key={key} value={key}>{label}</option>)}
        </select>
        <label className="sr-only" htmlFor="case-search">Search questions</label>
        <input id="case-search" className="case-search" type="search"
          placeholder="Find a question, IS number or topic" value={search}
          onChange={(event) => setSearch(event.target.value)} />
      </div>

      <p className="acceptance-note">
        These are review prompts, not canned answers. Check whether the response is grounded
        in the cited BIS record; the expected answer describes what a reviewer should see.
      </p>

      <section className="case-list" aria-label="Acceptance questions">
        {visible.map((item) => (
          <article className="case-card" key={item.id}>
            <div className="case-topline">
              <span className="case-id">{item.id}</span>
              <span className={`case-difficulty ${item.difficulty}`}>{item.difficulty}</span>
              <span className="case-category">{categoryNames[item.category] ?? item.category}</span>
              <span className="case-lang">{item.lang === "hi" ? "हिंदी" : "EN"}</span>
            </div>
            <p className="case-question">{item.query}</p>
            <div className="case-target">
              <span>Expected answer</span>
              <p>{item.expected_answer}</p>
            </div>
            <div className="case-bottomline">
              <div className="case-flags">
                {item.must_refuse && <span className="case-flag warn">Must refuse</span>}
                {item.must_cite && <span className="case-flag">BIS citation</span>}
                {item.expect_llm && <span className="case-flag">Qwen path</span>}
              </div>
              <button type="button" className="case-run" disabled={disabled}
                onClick={() => onAsk(item)}>
                Ask in chat <span aria-hidden="true">↗</span>
              </button>
            </div>
          </article>
        ))}
        {visible.length === 0 && <p className="case-empty">No matching questions. Try another topic or search.</p>}
      </section>
    </section>
  );
}
