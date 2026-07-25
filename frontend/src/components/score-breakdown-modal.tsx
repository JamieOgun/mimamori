"use client";

import { Maximize2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

type CriterionScore = {
  key: string;
  score: number;
};

type ScoreBreakdownModalProps = {
  category: "cognitive" | "emotional";
  criteria: CriterionScore[];
  markers?: string[];
  notes?: string;
  score: number;
};

export function ScoreBreakdownModal({
  category,
  criteria,
  markers = [],
  notes = "",
  score,
}: ScoreBreakdownModalProps) {
  const t = useTranslations("Dashboard");
  const [open, setOpen] = useState(false);
  const categoryLabel = t(category);

  useEffect(() => {
    if (!open) return;

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  return (
    <>
      <button
        aria-label={t("openScoreBreakdown", { category: categoryLabel })}
        className="expand-action"
        onClick={() => setOpen(true)}
        type="button"
      >
        <Maximize2 size={18} />
      </button>

      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <section
            aria-label={t("scoreBreakdownFor", { category: categoryLabel })}
            aria-modal="true"
            className="score-modal"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
          >
            <header>
              <div>
                <p>{t("scoreBreakdown")}</p>
                <h2>{categoryLabel}</h2>
              </div>
              <button
                aria-label={t("closeScoreBreakdown")}
                onClick={() => setOpen(false)}
                type="button"
              >
                <X size={20} />
              </button>
            </header>

            <section className="modal-score">
              <strong>{score}</strong>
              <span>{categoryLabel}</span>
            </section>

            <ul className="modal-criterion-list">
              {criteria.map((criterion) => (
                <li key={criterion.key}>
                  <div>
                    <span>{t(`criteria.${criterion.key}`)}</span>
                    <strong>{criterion.score}</strong>
                  </div>
                  <span className="criterion-track" aria-hidden="true">
                    <span style={{ width: `${criterion.score}%` }} />
                  </span>
                </li>
              ))}
            </ul>

            {markers.length > 0 && (
              <section className="assessment-evidence modal-evidence">
                <h3>{t("evidenceMarkers")}</h3>
                <div className="marker-list">
                  {markers.map((marker) => (
                    <span key={marker}>{marker}</span>
                  ))}
                </div>
              </section>
            )}

            {notes && (
              <section className="assessment-note modal-note">
                <h3>{t("assessmentNotes")}</h3>
                <p>{notes}</p>
              </section>
            )}
          </section>
        </div>
      )}
    </>
  );
}
