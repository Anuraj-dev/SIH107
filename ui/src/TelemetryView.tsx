import { AuditIcon, CheckIcon, DownloadIcon, RefreshIcon } from "./icons";
import type { ServerThread } from "./api";

interface TelemetryViewProps {
  healthy: boolean | null;
  thread: ServerThread | null;
  onRefreshHealth: () => void;
  onExport: () => void;
  turnCount: number;
}

export default function TelemetryView({
  healthy,
  thread,
  onRefreshHealth,
  onExport,
  turnCount,
}: TelemetryViewProps) {
  return (
    <div className="telemetry-container">
      <div className="directory-header">
        <div className="flex items-center gap-3 mb-2">
          <div className="admin-icon-box">
            <AuditIcon className="w-5 h-5 text-indigo-600" />
          </div>
          <div>
            <h2 className="directory-title">System Audit, Security & DPDP Compliance</h2>
            <p className="directory-subtitle">
              Live observability, privacy protections, and citation guardrails per Digital Personal Data Protection (DPDP) Act 2023.
            </p>
          </div>
        </div>
      </div>

      {/* Operational Metrics Cards */}
      <div className="telemetry-grid">
        <div className="telemetry-card">
          <div className="card-top">
            <span className="telemetry-label">Backend Connection</span>
            <button
              type="button"
              className="refresh-mini-btn"
              onClick={onRefreshHealth}
              title="Re-check health"
            >
              <RefreshIcon className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="telemetry-status-row">
            <span
              className={`status-dot-large ${
                healthy === null ? "unknown" : healthy ? "ok" : "down"
              }`}
            />
            <span className="telemetry-val">
              {healthy === null
                ? "Probing API…"
                : healthy
                ? "API Active & Synchronized"
                : "API Unreachable (Check Port 8000)"}
            </span>
          </div>
          <p className="telemetry-desc">
            FastAPI / stdlib microservice serving verified BIS metadata queries and BM25 RAG index.
          </p>
        </div>

        <div className="telemetry-card">
          <span className="telemetry-label">Session State & Continuity</span>
          <div className="telemetry-val-text font-mono">
            {thread ? `Thread #${thread.id.slice(0, 12)}…` : "Stateless / Single-Turn Active"}
          </div>
          <p className="telemetry-desc">
            {turnCount} dialogue turns in current session. Thread continuation uses cryptographic owner token validation.
          </p>
        </div>

        <div className="telemetry-card">
          <span className="telemetry-label">DPDP Act 2023 Guard</span>
          <div className="telemetry-badge-row">
            <span className="badge-shield">
              <CheckIcon className="w-3 h-3 text-emerald-600" />
              <span>PII Minimisation Enforced</span>
            </span>
          </div>
          <p className="telemetry-desc">
            Client & server regex automatically mask Indian mobile numbers (+91), email addresses, PAN, and 12-digit Aadhaar.
          </p>
        </div>
      </div>

      {/* Compliance Architecture Breakdown */}
      <div className="compliance-section">
        <h3 className="section-title">Citation & Grounding Invariants</h3>
        <div className="compliance-list">
          <div className="compliance-item">
            <div className="check-circle">
              <CheckIcon className="w-3.5 h-3.5 text-emerald-600" />
            </div>
            <div>
              <div className="compliance-title">Strict Allowlist Grounding</div>
              <p className="compliance-body">
                Responses are synthesized solely from allowlisted Bureau of Indian Standards metadata (Know Your Standard, DG Dashboard, CRS, LIMS). Unverified external claims trigger automated safety refusals.
              </p>
            </div>
          </div>

          <div className="compliance-item">
            <div className="check-circle">
              <CheckIcon className="w-3.5 h-3.5 text-emerald-600" />
            </div>
            <div>
              <div className="compliance-title">Transparent Citation Specification</div>
              <p className="compliance-body">
                Every recommended standard carries standard code, revision year, active/withdrawn status, last checked date, and an official hyperlinked verification portal URL.
              </p>
            </div>
          </div>

          <div className="compliance-item">
            <div className="check-circle">
              <CheckIcon className="w-3.5 h-3.5 text-emerald-600" />
            </div>
            <div>
              <div className="compliance-title">Two-Person Authorization for Knowledge Base Updates</div>
              <p className="compliance-body">
                Quality Control Order (QCO) updates, withdrawals, and revisions cannot be committed to production without dual cryptographic keys from both Publisher and Approver roles.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Export Action Card */}
      <div className="export-action-card">
        <div>
          <h4 className="font-semibold text-slate-900 mb-1">Export Redacted Audit Transcript</h4>
          <p className="text-xs text-slate-600">
            Download JSON session transcript with all PII scrubbed for offline compliance records.
          </p>
        </div>
        <button type="button" className="btn-primary-export" onClick={onExport}>
          <DownloadIcon className="w-4 h-4" />
          <span>Export Redacted JSON</span>
        </button>
      </div>
    </div>
  );
}
