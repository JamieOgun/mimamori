"use client";

import {
  Brain,
  CalendarClock,
  FileAudio,
  HeartPulse,
  ListFilter,
  Loader2,
  PhoneCall,
  X,
} from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";

import { LanguageSelect } from "../components/language-select";
import { ScoreBreakdownModal } from "../components/score-breakdown-modal";
import {
  callSummary,
  cognitiveCriteria,
  emotionalCriteria,
  formatCallDate,
  formatCallTime,
  scoreTone,
  type CallRecord,
} from "../data/calls";
import {
  fetchCalls,
  fetchCheckInResult,
  scheduleCheckInCall,
  startCheckInCall,
} from "../lib/api";

type RiskFilter = "All" | CallRecord["risk"];
type CallAction = "call" | "schedule" | null;
type CallNotice = { tone: "success" | "error"; text: string } | null;
type ActiveCall = { callSid: string; status: "calling" | "waiting" } | null;

const DEMO_TO_NUMBER = process.env.NEXT_PUBLIC_DEMO_TO_NUMBER ?? "";

function average(values: number[]) {
  if (values.length === 0) return 0;
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

function DetailedMetric({
  category,
  criteria,
  score,
}: {
  category: "cognitive" | "emotional";
  criteria: Array<{ key: string; score: number }>;
  score: number;
}) {
  const t = useTranslations("Dashboard");
  const Icon = category === "cognitive" ? Brain : HeartPulse;

  return (
    <article className="metric detailed-metric">
      <header>
        <div className="metric-heading">
          <Icon size={19} />
          <div>
            <p>{t(category)}</p>
            <strong>{score}</strong>
          </div>
        </div>
        <ScoreBreakdownModal
          category={category}
          criteria={criteria}
          score={score}
        />
      </header>
    </article>
  );
}

export default function HomePage() {
  const t = useTranslations("Dashboard");
  const locale = useLocale();
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("All");
  const [calls, setCalls] = useState<CallRecord[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [scheduledTime, setScheduledTime] = useState("");
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [callAction, setCallAction] = useState<CallAction>(null);
  const [callNotice, setCallNotice] = useState<CallNotice>(null);
  const [activeCall, setActiveCall] = useState<ActiveCall>(null);

  const refreshCalls = useCallback(async () => {
    const data = await fetchCalls();
    setCalls(data);
    setLoadError(false);
  }, []);

  useEffect(() => {
    fetchCalls()
      .then((data) => setCalls(data))
      .catch(() => {
        setLoadError(true);
      });
  }, []);

  useEffect(() => {
    if (!activeCall) return;

    const callSid = activeCall.callSid;
    let canceled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    async function pollResult() {
      try {
        const result = await fetchCheckInResult(callSid);
        if (canceled) return;

        if (result.status === "complete") {
          await refreshCalls();
          if (canceled) return;
          setCallNotice({
            tone: "success",
            text: t("callScoreReady", {
              score: result.scores.score,
              risk: result.scores.risk,
            }),
          });
          setActiveCall(null);
          return;
        }

        setActiveCall((current) =>
          current?.callSid === callSid && current.status !== "waiting"
            ? { ...current, status: "waiting" }
            : current,
        );
        timeoutId = setTimeout(pollResult, 3000);
      } catch {
        if (canceled) return;
        setCallNotice({ tone: "error", text: t("callResultError") });
        setActiveCall(null);
      }
    }

    timeoutId = setTimeout(pollResult, 3000);
    return () => {
      canceled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [activeCall, refreshCalls, t]);

  const dashboard = useMemo(() => {
    const source = calls ?? [];
    return {
      overall: average(source.map((call) => call.score)),
      cognitive: average(source.map((call) => call.cognitive.score)),
      emotional: average(source.map((call) => call.emotional.score)),
      cognitiveCriteria: cognitiveCriteria.map((key) => ({
        key,
        score: average(source.map((call) => call.cognitive.criteria[key])),
      })),
      emotionalCriteria: emotionalCriteria.map((key) => ({
        key,
        score: average(source.map((call) => call.emotional.criteria[key])),
      })),
      watchCount: source.filter((call) => call.risk !== "Low").length,
    };
  }, [calls]);

  const visibleCalls = useMemo(
    () =>
      (calls ?? []).filter(
        (call) => riskFilter === "All" || call.risk === riskFilter,
      ),
    [calls, riskFilter],
  );

  async function handleStartCall() {
    const to = DEMO_TO_NUMBER.trim();
    if (!to) {
      setCallNotice({ tone: "error", text: t("demoPhoneNumberMissing") });
      return;
    }

    setCallAction("call");
    setCallNotice(null);
    try {
      const response = await startCheckInCall(to);
      setActiveCall({ callSid: response.call_sid, status: "calling" });
      setCallNotice({
        tone: "success",
        text: t("callStarted", { callSid: response.call_sid }),
      });
    } catch {
      setCallNotice({ tone: "error", text: t("callStartError") });
    } finally {
      setCallAction(null);
    }
  }

  async function handleScheduleCall() {
    const to = DEMO_TO_NUMBER.trim();
    if (!to) {
      setCallNotice({ tone: "error", text: t("demoPhoneNumberMissing") });
      return;
    }

    if (!scheduledTime) {
      setCallNotice({ tone: "error", text: t("scheduleTimeRequired") });
      return;
    }

    setCallAction("schedule");
    setCallNotice(null);
    try {
      const response = await scheduleCheckInCall(to, scheduledTime);
      const formattedTime = new Intl.DateTimeFormat(locale, {
        timeZone: "Asia/Tokyo",
        timeStyle: "short",
      }).format(new Date(response.next_run_at));
      setCallNotice({
        tone: "success",
        text: t("callScheduled", { time: formattedTime }),
      });
      setScheduleDialogOpen(false);
    } catch {
      setCallNotice({ tone: "error", text: t("callScheduleError") });
    } finally {
      setCallAction(null);
    }
  }

  return (
    <main className="app-shell">
      <section className="workspace dashboard-workspace">
        <header className="topbar">
          <h1 className="brand-title">
            <img alt="mimamori" src="/image.png" />
          </h1>
          <div className="topbar-actions">
            <button
              className="primary-action"
              disabled={callAction !== null || activeCall !== null}
              onClick={handleStartCall}
              type="button"
            >
              {callAction === "call" || activeCall ? (
                <Loader2 className="spin" size={18} />
              ) : (
                <PhoneCall size={18} />
              )}
              {activeCall
                ? t(
                    activeCall.status === "calling"
                      ? "callInProgress"
                      : "callWaitingForScore",
                  )
                : t("startDemoCall")}
            </button>
            <div className="schedule-menu">
              <button
                aria-expanded={scheduleDialogOpen}
                aria-haspopup="dialog"
                className="secondary-action"
                disabled={callAction !== null || activeCall !== null}
                onClick={() => setScheduleDialogOpen(true)}
                type="button"
              >
                <CalendarClock size={18} />
                {t("scheduleCall")}
              </button>

              {scheduleDialogOpen && (
                <div
                  aria-label={t("scheduleCall")}
                  className="schedule-popover"
                  role="dialog"
                >
                  <header>
                    <strong>{t("scheduleCall")}</strong>
                    <button
                      aria-label={t("closeScheduleDialog")}
                      onClick={() => setScheduleDialogOpen(false)}
                      type="button"
                    >
                      <X size={16} />
                    </button>
                  </header>
                  <label>
                    <span>{t("scheduleTime")}</span>
                    <input
                      autoFocus
                      onChange={(event) => setScheduledTime(event.target.value)}
                      type="time"
                      value={scheduledTime}
                    />
                  </label>
                  <div className="schedule-popover-actions">
                    <button
                      className="secondary-action"
                      onClick={() => setScheduleDialogOpen(false)}
                      type="button"
                    >
                      {t("cancel")}
                    </button>
                    <button
                      className="primary-action"
                      disabled={callAction !== null || activeCall !== null}
                      onClick={handleScheduleCall}
                      type="button"
                    >
                      {callAction === "schedule" ? (
                        <Loader2 className="spin" size={18} />
                      ) : (
                        <CalendarClock size={18} />
                      )}
                      {t("scheduleCall")}
                    </button>
                  </div>
                </div>
              )}
            </div>
            <LanguageSelect />
            <label className="filter-control">
              <ListFilter size={18} />
              <select
                aria-label={t("filterCallsByRisk")}
                onChange={(event) => setRiskFilter(event.target.value as RiskFilter)}
                value={riskFilter}
              >
                <option value="All">{t("risk.all")}</option>
                <option value="Low">{t("risk.low")}</option>
                <option value="Watch">{t("risk.watch")}</option>
                <option value="High">{t("risk.high")}</option>
              </select>
            </label>
          </div>
        </header>

        {callNotice && (
          <p
            aria-live="polite"
            className={`call-action-status header-call-status ${callNotice.tone}`}
          >
            {callNotice.text}
          </p>
        )}

        <section className="score-overview" aria-label={t("scoreOverview")}>
          <article className="overall-score">
            <div>
              <p>{t("averageScore")}</p>
              <div className="overall-value">
                <strong>{dashboard.overall}</strong>
              </div>
            </div>
          </article>

          <DetailedMetric
            category="cognitive"
            criteria={dashboard.cognitiveCriteria}
            score={dashboard.cognitive}
          />
          <DetailedMetric
            category="emotional"
            criteria={dashboard.emotionalCriteria}
            score={dashboard.emotional}
          />
        </section>

        <section className="call-list" aria-label={t("callRecordings")}>
          <div className="section-heading">
            <div>
              <p>{t("recentRecordings")}</p>
              <h2>{t("transcriptsAndScores")}</h2>
            </div>
          </div>

          <div className="table-shell">
            <table>
              <thead>
                <tr>
                  <th>{t("table.call")}</th>
                  <th>{t("table.score")}</th>
                  <th>{t("table.risk")}</th>
                  <th>{t("table.duration")}</th>
                </tr>
              </thead>
              <tbody>
                {visibleCalls.map((call) => (
                  <tr key={call.id}>
                    <td>
                      <Link className="call-cell" href={`/calls/${call.id}`}>
                        <FileAudio size={18} />
                        <span>
                          <strong>
                            {formatCallDate(call.startedAt, locale)} ·{" "}
                            {formatCallTime(call.startedAt, locale)}
                          </strong>
                          <small>{callSummary(call)}</small>
                        </span>
                      </Link>
                    </td>
                    <td>
                      <span className={`score-dot ${scoreTone(call.score)}`} />
                      {call.score}
                    </td>
                    <td>
                      <span className={`risk-label ${call.risk.toLowerCase()}`}>
                        {t(`risk.${call.risk.toLowerCase()}`)}
                      </span>
                    </td>
                    <td>
                      {t("durationValue", {
                        minutes: call.durationMinutes,
                        seconds: call.durationSeconds,
                      })}
                    </td>
                  </tr>
                ))}
                {visibleCalls.length === 0 && (
                  <tr>
                    <td className="empty-table" colSpan={4}>
                      {calls === null && !loadError
                        ? t("loadingCalls")
                        : loadError
                          ? t("loadError")
                          : t("noMatchingCalls")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  );
}
