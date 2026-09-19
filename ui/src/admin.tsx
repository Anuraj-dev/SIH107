import { useState } from "react";
import { fetchKbDiff, publishKbDiff } from "./api";
import type { KbDiff } from "./types";
import { DiffIcon, CheckIcon, AlertTriangleIcon, ExternalLinkIcon } from "./icons";

/**
 * Admin diff-review dashboard: gated behind a live admin key,
 * pending diffs from GET /kb/diff, publish via POST /kb/publish.
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
      setStatus("Enter the primary publisher/admin key first.");
      return;
    }
    setLoading(true);
    setStatus("");
    try {
      const { diff: d, fixture: f } = await fetchKbDiff(publisherKey.trim());
      if (f) {
        setUnlocked(false);
        setDiff(null);
        setStatus("Live pending diff required — fixture unlock is disabled for security.");
        return;
      }
      setDiff(d);
      setFixture(false);
      setUnlocked(true);
      setStatus("Loaded live pending KB diff successfully.");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      setUnlocked(false);
      setDiff(null);
      setStatus(
        /HTTP 403/.test(msg)
          ? "Admin access key was rejected (HTTP 403 Forbidden)."
          : `Unable to load KB diff${msg ? `: ${msg}` : "."}`,
      );
    } finally {
      setLoading(false);
    }
  };

  const decide = async (changeId: string, decision: "approve" | "reject") => {
    if (!diff) return;
    setStatus("");
    const res = await publishKbDiff(changeId, decision, publisherKey, approverKey);
    setDecisions((d) => ({ ...d, [changeId]: decision }));
    const verb = decision === "approve" ? "Approved" : "Rejected";
    setStatus(
      res.ok
        ? `${verb} standard change ${changeId} (${res.fixture ? "recorded locally — fixture endpoint" : "live POST /kb/publish"}).`
        : `Could not record ${decision} for ${changeId}: ${res.error ?? "request failed"}.`,
    );
  };

  if (!unlocked || !diff) {
    return (
      <section className="admin-container" aria-labelledby="admin-h">
        <div className="admin-header">
          <div className="admin-title-group">
            <div className="admin-icon-box">
              <DiffIcon size={20} />
            </div>
            <div>
              <h2 id="admin-h" className="admin-title">
                Knowledge Base Diff & Review Console
              </h2>
              <p className="admin-subtitle">
                Two-person authorization gate for official BIS standard metadata changes.
              </p>
            </div>
          </div>
        </div>

        <div className="admin-security-note">
          <AlertTriangleIcon size={16} />
          <div className="telemetry-desc">
            <strong>Dual-Key Protocol Required for Live Publishing:</strong> Reviewing pending diffs requires
            an active administrative key (<code>GET /kb/diff</code>). Publishing approval or rejection to the live
            knowledge base requires two distinct administrative keys (Publisher + Approver).
          </div>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            load();
          }}
          className="admin-form-card"
        >
          <div className="form-group">
            <label htmlFor="admin-token" className="form-label">
              Publisher Key <span aria-hidden="true">*</span>
            </label>
            <input
              id="admin-token"
              type="password"
              autoComplete="off"
              value={publisherKey}
              onChange={(e) => setPublisherKey(e.target.value)}
              placeholder="Paste primary publisher key…"
              className="admin-input"
            />
          </div>

          <div className="form-group">
            <label htmlFor="admin-approver" className="form-label">
              Approver Key <span className="hint-tag">(Required for 2-person live publish)</span>
            </label>
            <input
              id="admin-approver"
              type="password"
              autoComplete="off"
              value={approverKey}
              onChange={(e) => setApproverKey(e.target.value)}
              placeholder="Paste distinct 2nd approver key…"
              className="admin-input"
            />
          </div>

          <div className="form-actions">
            <button
              type="submit"
              className="btn-primary-admin"
              disabled={loading || !publisherKey.trim()}
            >
              {loading ? "Authenticating…" : "Unlock Diff Review"}
            </button>
          </div>
        </form>

        {status && (
          <div className="admin-status-alert" role="status">
            {status}
          </div>
        )}
      </section>
    );
  }

  const addedCount = diff.changes.filter((c) => c.change === "added").length;
  const changedCount = diff.changes.filter((c) => c.change === "changed").length;
  const warnCount = diff.changes.filter(
    (c) => c.change === "withdrawn" || c.change === "missing-upstream",
  ).length;

  return (
    <section className="admin-container" aria-labelledby="admin-h">
      <div className="admin-header flex-between">
        <div className="admin-title-group">
          <div className="admin-icon-box">
            <DiffIcon size={20} />
          </div>
          <div>
            <h2 id="admin-h" className="admin-title">
              Pending KB Standard Diffs
            </h2>
            <div className="admin-meta-info">
              <span>Diff ID: <code>{diff.diff_id}</code></span>
              <span>·</span>
              <span>Generated: {new Date(diff.generated_at).toLocaleString()}</span>
              <span>·</span>
              <span className="badge-live">{fixture ? "Fixture Stub" : "Live Backend"}</span>
            </div>
          </div>
        </div>

        <button
          type="button"
          className="btn-lock-screen"
          onClick={() => {
            setUnlocked(false);
            setDiff(null);
            setDecisions({});
            setStatus("Session locked.");
          }}
        >
          Lock Console
        </button>
      </div>

      {/* Metrics strip */}
      <div className="admin-stats-grid">
        <div className="stat-card">
          <div className="stat-num">{diff.changes.length}</div>
          <div className="stat-lbl">Pending Changes</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{addedCount}</div>
          <div className="stat-lbl">New Standards</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{changedCount}</div>
          <div className="stat-lbl">Modified Specifications</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{warnCount}</div>
          <div className="stat-lbl">Withdrawn / Missing</div>
        </div>
      </div>

      {status && (
        <div className="admin-status-alert" role="status">
          {status}
        </div>
      )}

      <div className="tablewrap">
        <table className="difftable">
          <caption className="sr-only">KB snapshot changes awaiting dual-person review</caption>
          <thead>
            <tr>
              <th scope="col">Standard / Snapshot</th>
              <th scope="col">Change Nature</th>
              <th scope="col">Status Transition</th>
              <th scope="col">Verification Source</th>
              <th scope="col">Audit Decision</th>
            </tr>
          </thead>
          <tbody>
            {diff.changes.map((c) => {
              const isWarningRow = c.change === "withdrawn" || c.change === "missing-upstream";
              return (
                <tr key={c.id} className={isWarningRow ? "row-warn" : ""}>
                  <td>
                    <div className="font-mono"><strong>{c.is_number}</strong></div>
                    {c.snapshot_id != null && (
                      <div className="text-xs">Snapshot #{c.snapshot_id}</div>
                    )}
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        c.change === "added"
                          ? "ok"
                          : c.change === "withdrawn" || c.change === "missing-upstream"
                          ? "refuse"
                          : "lang"
                      }`}
                    >
                      {c.change}
                    </span>
                  </td>
                  <td>
                    {c.old_status != null || c.new_status != null ? (
                      <div className="status-flow">
                        <span className="old-st">{c.old_status ?? "—"}</span>
                        <span className="arrow-st">→</span>
                        <span className="new-st">{c.new_status ?? "—"}</span>
                      </div>
                    ) : (
                      <span className="text-xs">{c.details ?? "—"}</span>
                    )}
                  </td>
                  <td>
                    {c.source_url && /^https?:\/\//i.test(c.source_url) ? (
                      <a
                        href={c.source_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <span>BIS Portal Source</span>
                        <span className="sr-only"> (opens in new tab)</span>
                        <ExternalLinkIcon size={12} />
                      </a>
                    ) : (
                      <span className="text-xs">{c.details ?? "No external URL"}</span>
                    )}
                    {c.last_checked && (
                      <div className="text-xs">Verified: {c.last_checked}</div>
                    )}
                  </td>
                  <td>
                    {decisions[c.id] ? (
                      <div className="decided-badge">
                        <CheckIcon size={14} />
                        <span className="capitalize">
                          {decisions[c.id]}ed
                        </span>
                      </div>
                    ) : (
                      <div className="decide-actions">
                        <button
                          type="button"
                          className="btn-decide-approve"
                          onClick={() => decide(c.id, "approve")}
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          className="btn-decide-reject"
                          onClick={() => decide(c.id, "reject")}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
