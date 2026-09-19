import { CERTIFICATION_SCHEMES, type SchemeItem } from "./standardsData";
import { SchemesIcon, ExternalLinkIcon, ChatIcon } from "./icons";

interface SchemesViewProps {
  onSelectQuery: (query: string) => void;
}

export default function SchemesView({ onSelectQuery }: SchemesViewProps) {
  return (
    <div className="schemes-container">
      <div className="directory-header">
        <div className="view-header">
          <div className="admin-icon-box">
            <SchemesIcon size={20} />
          </div>
          <div>
            <h2 className="directory-title">BIS Certification &amp; Conformity Assessment Schemes</h2>
            <p className="directory-subtitle">
              Official conformity assessment frameworks administered under the Bureau of Indian Standards Act, 2016.
            </p>
          </div>
        </div>
      </div>

      <div className="schemes-grid">
        {CERTIFICATION_SCHEMES.map((scheme: SchemeItem) => (
          <div key={scheme.key} className="scheme-card">
            <div className="scheme-header">
              <span className="scheme-key-badge">{scheme.key}</span>
              <div>
                <h3 className="scheme-name-en">{scheme.name_en}</h3>
                <p className="scheme-name-hi">{scheme.name_hi}</p>
              </div>
            </div>

            <div className="scheme-suitability">
              <span className="suitability-label">Scope & Suitability:</span>
              <p className="suitability-text">{scheme.suitable_for}</p>
            </div>

            <div className="scheme-process-block">
              <span className="process-label">Licensing & Conformity Flow:</span>
              <ol className="process-steps">
                {scheme.process_en.map((step, idx) => (
                  <li key={idx} className="process-step-item">
                    <span className="step-num">{idx + 1}</span>
                    <span className="step-text">{step}</span>
                  </li>
                ))}
              </ol>
            </div>

            <div className="scheme-footer-actions">
              <button
                type="button"
                className="btn-query-assistant"
                onClick={() => onSelectQuery(scheme.sample_query)}
              >
                <ChatIcon size={14} />
                <span>Ask Process Guidance</span>
              </button>
              <a
                href={scheme.apply_at}
                target="_blank"
                rel="noreferrer"
                className="btn-bis-portal"
              >
                <span>Apply on Portal</span>
                <span className="sr-only"> (opens in new tab)</span>
                <ExternalLinkIcon size={12} />
              </a>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
