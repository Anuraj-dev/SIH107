import { CERTIFICATION_SCHEMES, type SchemeItem } from "./standardsData";
import { SchemesIcon, ExternalLinkIcon, ChatIcon } from "./icons";

interface SchemesViewProps {
  onSelectQuery: (query: string) => void;
}

export default function SchemesView({ onSelectQuery }: SchemesViewProps) {
  return (
    <div className="schemes-container">
      <div className="directory-header">
        <div className="flex items-center gap-3 mb-2">
          <div className="admin-icon-box">
            <SchemesIcon className="w-5 h-5 text-indigo-600" />
          </div>
          <div>
            <h2 className="directory-title">BIS Certification & Conformity Assessment Schemes</h2>
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
                onClick={() =>
                  onSelectQuery(
                    `What is the step-by-step application procedure and testing requirements for ${scheme.key} certification?`,
                  )
                }
              >
                <ChatIcon className="w-3.5 h-3.5" />
                <span>Ask Process Guidance</span>
              </button>
              <a
                href={scheme.apply_at}
                target="_blank"
                rel="noreferrer"
                className="btn-bis-portal"
              >
                <span>Apply on Portal</span>
                <ExternalLinkIcon className="w-3 h-3" />
              </a>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
