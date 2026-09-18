import { useState } from "react";
import { fetchKbDiff, publishKbDiff } from "./api";
import type { KbDiff } from "./types";

/**
 * Admin diff-review screen (plan §5): gated behind a token input,
 * fixture-driven table with approve/reject per diff hitting fixture endpoints.
 */
export default function AdminPanel() {
  const [publisherKey, setPublisherKey] = useState("");
  const [approverKey, setApproverKey] = useState("");
  const [unlocked, setUnlocked] = useState(false);
  const [diff, setDiff] = useState<KbDiff | null>(null);
  const [fixture, setFixture] = useState(false);
  const [loading, setLoading] = useState(false);
  const [decisions, setDecisions] = useState<Record<string, "approve" | "reject">>({});
  const [status, setStatus] = useState("");

  const load = async () => {
    if (!publisherKey.trim()) {
      setStatus("Enter the publisher/admin key first.");
      return;
    }
    setLoading(true);
    setStatus("");
    try {
      const { diff: d, fixture: f } = await fetchKbDiff(publisherKey.trim());
      setDiff(d);
      setFixture(f);
      setUnlocked(true);
      setStatus(f ? "Showing fixture diff (live GET /kb/diff not available)." : "Loaded live diff.");
    } catch {
      setStatus("Could not load the KB diff.");
    } finally {
      setLoading(false);
    }
  };

  const decide = async (changeId: string, decision: "approve" | "reject") => {
    if (!diff) return;
    setStatus("");
    const res = await publishKbDiff(diff.diff_id, decision, publisherKey, approverKey);
    setDecisions((d) => ({ ...d, [changeId]: decision }));
    setStatus(
      `Recorded ${decision} for ${changeId} (${res.fixture ? "fixture endpoint" : "live POST /kb/publish"}).`,
    );
  };

  if (!unlocked || !diff) {
    return (
      <section className="admin" aria-labelledby="admin-h">
        <h2 id="admin-h">Admin — KB diff review</h2>
        <p className="hint">
          Reviewer-gated. Publishing needs two distinct approvers (plan §6): enter both keys for a
          live <code>POST /kb/publish</code>, or just the publisher key for a fixture review until
          the admin backend is reachable. Diff list loads via <code>GET /kb/diff</code> (x-admin-key).
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            load();
          }}
          className="admin-gate"
        >
          <label htmlFor="admin-token">Publisher key</label>
          <input
            id="admin-token"
            type="password"
            autoComplete="off"
            value={publisherKey}
            onChange={(e) => setPublisherKey(e.target.value)}
            placeholder="paste publisher key"
          />
          <label htmlFor="admin-approver">Approver key <span className="hint">(distinct 2nd key for live publish)</span></label>
          <input
            id="admin-approver"
            type="password"
            autoComplete="off"
            value={approverKey}
            onChange={(e) => setApproverKey(e.target.value)}
            placeholder="paste distinct approver key (optional)"
          />
          <button type="submit" className="primary" disabled={loading || !publisherKey.trim()}>
            {loading ? "…" : "Unlock diff"}
          </button>
        </form>
        {status && <p className="hint" role="status">{status}</p>}
      </section>
    );
  }

  return (
    <section className="admin" aria-labelledby="admin-h">
      <h2 id="admin-h">Admin — KB diff review</h2>
      <p className="hint">
        Diff <code>{diff.diff_id}</code> · generated {diff.generated_at} ·{" "}
        {fixture ? "fixture data (backend stub)" : "live backend data"} · {diff.changes.length} change(s)
      </p>
      {status && <p className="hint" role="status">{status}</p>}
      <div className="tablewrap">
        <table className="difftable">
          <caption className="sr-only">KB snapshot changes awaiting review</caption>
          <thead>
            <tr>
              <th scope="col">IS</th>
              <th scope="col">Change</th>
              <th scope="col">Old → New</th>
              <th scope="col">Source</th>
              <th scope="col">Decision</th>
            </tr>
          </thead>
          <tbody>
            {diff.changes.map((c) => (
              <tr key={c.id} className={c.change === "withdrawn" || c.change === "missing-upstream" ? "row-warn" : ""}>
                <td>{c.is_number}{c.snapshot_id != null && <div className="hint">snapshot #{c.snapshot_id}</div>}</td>
                <td>
                  <span className={`badge ${c.change === "withdrawn" || c.change === "missing-upstream" ? "refuse" : "lang"}`}>{c.change}</span>
                </td>
                <td>
                  {c.old_status != null || c.new_status != null
                    ? `${c.old_status ?? "—"} → ${c.new_status ?? "—"}`
                    : (c.details ?? "—")}
                </td>
                <td>
                  {c.source_url ? (
                    <a href={c.source_url} target="_blank" rel="noreferrer">{c.source_url}</a>
                  ) : (
                    <span className="hint">{c.details ?? "no source link"}</span>
                  )}
                  {c.last_checked && <div className="hint">checked {c.last_checked}</div>}
                </td>
                <td>
                  {decisions[c.id] ? (
                    <span className="badge ok">{decisions[c.id]}d</span>
                  ) : (
                    <div className="decide">
                      <button type="button" className="ghost" onClick={() => decide(c.id, "approve")}>
                        Approve
                      </button>
                      <button type="button" className="ghost danger" onClick={() => decide(c.id, "reject")}>
                        Reject
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="button" className="ghost" onClick={() => { setUnlocked(false); setDiff(null); setDecisions({}); }}>
        Lock screen
      </button>
    </section>
  );
}
