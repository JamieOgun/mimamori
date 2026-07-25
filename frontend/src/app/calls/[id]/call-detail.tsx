"use client";

import {
  AlertCircle,
  ArrowLeft,
  Brain,
  FileAudio,
  HeartPulse,
} from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { LanguageSelect } from "../../../components/language-select";
import {
  cognitiveCriteria,
  emotionalCriteria,
  formatCallDate,
  formatCallTime,
  silentRecording,
  type CallRecord,
} from "../../../data/calls";

function AssessmentCard({
  category,
  criteria,
  markers,
  notes,
  score,
}: {
  category: "cognitive" | "emotional";
  criteria: Array<{ key: string; score: number }>;
  markers: string[];
  notes: string;
  score: number;
}) {
  const t = useTranslations("Dashboard");
  const Icon = category === "cognitive" ? Brain : HeartPulse;

  return (
    <article className="assessment-card">
      <header>
        <div>
          <Icon size={19} />
          <h2>{t(category)}</h2>
        </div>
        <strong>{score}</strong>
      </header>

      <ul className="criterion-list">
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
        <section className="assessment-evidence">
          <h3>{t("evidenceMarkers")}</h3>
          <div className="marker-list">
            {markers.map((marker) => (
              <span key={marker}>{marker}</span>
            ))}
          </div>
        </section>
      )}

      {notes && (
        <section className="assessment-note">
          <h3>{t("assessmentNotes")}</h3>
          <p>{notes}</p>
        </section>
      )}
    </article>
  );
}

export function CallDetail({ call }: { call: CallRecord }) {
  const t = useTranslations("Dashboard");
  const locale = useLocale();
  const recipientName = call.toNumber ?? t("careRecipient");

  return (
    <main className="app-shell">
      <section className="workspace detail-workspace">
        <header className="detail-toolbar">
          <Link className="back-link" href="/">
            <ArrowLeft size={18} />
            {t("backToDashboard")}
          </Link>
          <LanguageSelect />
        </header>

        <article className="call-detail-page">
          <header className="detail-page-header">
            <div>
              <p>
                {formatCallDate(call.startedAt, locale)} ·{" "}
                {formatCallTime(call.startedAt, locale)}
              </p>
              <h1>{recipientName}</h1>
              <span className="call-reference">
                {t("callReference")}: {call.id}
              </span>
            </div>
            <span className={`risk-label ${call.risk.toLowerCase()}`}>
              {t(`risk.${call.risk.toLowerCase()}`)}
            </span>
          </header>

          <section className="selected-score detail-score">
            <div className="score-value">
              <strong>{call.score}</strong>
            </div>
            <div>
              <p>{t("callScore")}</p>
              <span>
                {t("durationValue", {
                  minutes: call.durationMinutes,
                  seconds: call.durationSeconds,
                })}
              </span>
            </div>
          </section>

          <div className="score-breakdown">
            <span>
              {t("cognitive")} <strong>{call.cognitive.score}</strong>
            </span>
            <span>
              {t("emotional")} <strong>{call.emotional.score}</strong>
            </span>
          </div>

          <section className="assessment-grid">
            <AssessmentCard
              category="cognitive"
              criteria={cognitiveCriteria.map((key) => ({
                key,
                score: call.cognitive.criteria[key],
              }))}
              markers={call.cognitive.markers}
              notes={call.cognitive.notes}
              score={call.cognitive.score}
            />
            <AssessmentCard
              category="emotional"
              criteria={emotionalCriteria.map((key) => ({
                key,
                score: call.emotional.criteria[key],
              }))}
              markers={call.emotional.markers}
              notes={call.emotional.notes}
              score={call.emotional.score}
            />
          </section>

          <section className="audio-panel detail-audio">
            <div>
              <FileAudio size={17} />
              <span>{call.id}</span>
            </div>
            <audio
              aria-label={t("callRecording")}
              controls
              src={silentRecording}
            />
          </section>

          <section className="transcript-panel detail-transcript">
            <div className="section-heading compact">
              <div>
                <p>{t("transcript")}</p>
                <h2>{t("turnsCount", { count: call.transcript.length })}</h2>
              </div>
              <AlertCircle size={17} />
            </div>

            <div className="transcript-list">
              {call.transcript.map((turn, index) => (
                <article key={`${call.id}-${index}`}>
                  <time>{turn.time}</time>
                  <div>
                    <strong>
                      {turn.speaker === "Recipient"
                        ? t("speaker.recipient")
                        : turn.speaker}
                    </strong>
                    <p>{turn.text}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </article>
      </section>
    </main>
  );
}
