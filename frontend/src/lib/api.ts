import type { CallRecord } from "../data/calls";

// Base URL of the MimaMori backend (mimamori.main:app). Overridable per
// environment; defaults to the local dev server on port 6060.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

/**
 * Fetch all scored calls from the backend (`GET /calls`). The backend reads the
 * `data/transcripts` folder — the source of truth — and returns records in the
 * {@link CallRecord} shape, so no client-side reshaping is needed.
 */
export async function fetchCalls(): Promise<CallRecord[]> {
  const res = await fetch(`${API_BASE_URL}/calls`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /calls failed: ${res.status}`);
  return res.json();
}

/** Fetch one scored call by id (`GET /calls/{id}`), or null if not found. */
export async function fetchCall(id: string): Promise<CallRecord | null> {
  const res = await fetch(`${API_BASE_URL}/calls/${id}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GET /calls/${id} failed: ${res.status}`);
  return res.json();
}

export type CheckInResponse = {
  call_sid: string;
  to: string;
  status: "calling";
  result_url: string;
};

export type CheckInResultResponse =
  | {
      call_sid: string;
      status: "pending";
    }
  | {
      call_sid: string;
      status: "complete";
      transcript: string;
      scores: {
        score: number;
        risk: "Low" | "Watch" | "High";
      };
    };

export type ScheduledCallResponse = {
  schedule_id: string;
  to: string;
  call_time: string;
  timezone: string;
  next_run_at: string;
  status: "scheduled" | "calling" | "complete" | "failed";
  last_call_sid: string | null;
  error: string | null;
};

/** Start one outbound check-in call immediately (`POST /check-in`). */
export async function startCheckInCall(to: string): Promise<CheckInResponse> {
  const res = await fetch(`${API_BASE_URL}/check-in`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to }),
  });
  if (!res.ok) throw new Error(`POST /check-in failed: ${res.status}`);
  return res.json();
}

/** Fetch a check-in call's scoring state (`GET /result/{callSid}`). */
export async function fetchCheckInResult(
  callSid: string,
): Promise<CheckInResultResponse> {
  const res = await fetch(`${API_BASE_URL}/result/${callSid}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /result/${callSid} failed: ${res.status}`);
  return res.json();
}

/** Schedule one outbound check-in call (`POST /schedule-call`). */
export async function scheduleCheckInCall(
  to: string,
  callTime: string,
): Promise<ScheduledCallResponse> {
  const res = await fetch(`${API_BASE_URL}/schedule-call`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, call_time: callTime }),
  });
  if (!res.ok) throw new Error(`POST /schedule-call failed: ${res.status}`);
  return res.json();
}
