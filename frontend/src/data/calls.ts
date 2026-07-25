// Call records are sourced entirely from the backend (the `data/transcripts`
// folder is the database — see `lib/api.ts`). This file holds only the shared
// types, criteria enums, and pure display helpers — no hardcoded call data.

export const cognitiveCriteria = [
  "repetition",
  "temporalConfusion",
  "wordFinding",
  "confabulation",
  "vocabulary",
  "coherence",
] as const;

export const emotionalCriteria = [
  "affect",
  "anxiety",
  "withdrawal",
  "interest",
  "overallMood",
] as const;

export type CognitiveCriterion = (typeof cognitiveCriteria)[number];
export type EmotionalCriterion = (typeof emotionalCriteria)[number];

export type TranscriptTurn = {
  time: string;
  speaker: "MimaMori" | "Recipient";
  text: string;
};

export type Assessment<TCriterion extends string> = {
  score: number;
  criteria: Record<TCriterion, number>;
  // Real grader output: short evidence labels and a prose assessment note.
  markers: string[];
  notes: string;
};

// Mirrors the backend `GET /calls` shape (mimamori/calls.py).
export type CallRecord = {
  id: string;
  toNumber: string | null;
  startedAt: string | null;
  durationMinutes: number;
  durationSeconds: number;
  score: number;
  risk: "Low" | "Watch" | "High";
  cognitive: Assessment<CognitiveCriterion>;
  emotional: Assessment<EmotionalCriterion>;
  transcript: TranscriptTurn[];
};

export const silentRecording =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";

export function scoreTone(score: number) {
  if (score >= 80) return "strong";
  if (score >= 65) return "watch";
  return "risk";
}

/** Format a call's start timestamp as a locale-aware date (Asia/Tokyo). */
export function formatCallDate(startedAt: string | null, locale: string) {
  if (!startedAt) return "";
  return new Intl.DateTimeFormat(locale, {
    timeZone: "Asia/Tokyo",
    dateStyle: "medium",
  }).format(new Date(startedAt));
}

/** Format a call's start timestamp as a locale-aware time (Asia/Tokyo). */
export function formatCallTime(startedAt: string | null, locale: string) {
  if (!startedAt) return "";
  return new Intl.DateTimeFormat(locale, {
    timeZone: "Asia/Tokyo",
    timeStyle: "short",
  }).format(new Date(startedAt));
}

/** A short one-line summary derived from the recipient's first utterance. */
export function callSummary(call: CallRecord) {
  const firstReply = call.transcript.find(
    (turn) => turn.speaker === "Recipient",
  );
  if (!firstReply) return "";
  const text = firstReply.text.trim();
  return text.length > 64 ? `${text.slice(0, 64)}…` : text;
}
