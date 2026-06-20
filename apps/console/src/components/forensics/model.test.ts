import { describe, expect, it } from "vitest";

import type { AnalysisResult, ReplayArtifact, TraceEvent, TraceSession } from "@/lib/types";
import {
  evidenceSeqs,
  inferModality,
  offsetForEvent,
  selectionReducer,
  voiceMetadata,
} from "./model";

const session: TraceSession = {
  id: "ses_test",
  workspace_id: "ws_test",
  project_id: "prj_test",
  user_goal: "Cancel the order",
  agent: "voice-agent@1",
  environment: "test",
  status: "failed",
  tags: ["voice"],
  metadata: { modality: "voice" },
  started_at: "2026-06-18T00:00:00Z",
  event_count: 1,
  duration_ms: 1000,
  incident_id: "inc_test",
};

const event: TraceEvent = {
  type: "user_message",
  session_id: session.id,
  timestamp: session.started_at,
  seq: 4,
  idempotency_key: "test-4",
  t_offset_ms: 800,
  payload: {
    content: "No, cancel it",
    metadata: {
      channel: "voice",
      speaker: "user",
      start_ms: 800,
      end_ms: 1200,
      interrupted: true,
      sentiment: -0.5,
    },
  },
};

describe("forensic console model", () => {
  it("keeps replay selection synchronized and exits live-follow on manual selection", () => {
    const selected = selectionReducer(
      { selectedSeq: null, currentMs: 0, followLive: true, inspectorTab: "summary" },
      { type: "select", seq: 4, currentMs: 800 },
    );
    expect(selected).toMatchObject({ selectedSeq: 4, currentMs: 800, followLive: false });

    const live = selectionReducer(selected, { type: "go-live", seq: 9, currentMs: 2000 });
    expect(live).toMatchObject({ selectedSeq: 9, currentMs: 2000, followLive: true });
  });

  it("restores inspector tabs without disturbing replay state", () => {
    const state = { selectedSeq: 4, currentMs: 800, followLive: false, inspectorTab: "summary" as const };
    expect(selectionReducer(state, { type: "tab", tab: "metadata" })).toEqual({ ...state, inspectorTab: "metadata" });
  });

  it("uses artifact time maps before raw offsets", () => {
    const artifact: ReplayArtifact = {
      artifact_id: "art_test",
      session_id: session.id,
      storage_path: "/test.wav",
      content_type: "audio/wav",
      size_bytes: 100,
      event_time_map: { "4": 1.25 },
      duration_s: 2,
      kind: "audio",
    };
    expect(offsetForEvent(event, artifact)).toBe(1250);
    expect(offsetForEvent(event)).toBe(800);
  });

  it("infers voice modality and parses standardized voice metadata", () => {
    expect(inferModality(session, [])).toBe("voice");
    expect(voiceMetadata(event)).toMatchObject({ speaker: "user", interrupted: true, sentiment: -0.5 });
  });

  it("deduplicates evidence refs across detections", () => {
    const analysis = {
      detections: [{ evidence_refs: [1, 4] }, { evidence_refs: [4, 8] }],
    } as AnalysisResult;
    expect(evidenceSeqs(analysis)).toEqual([1, 4, 8]);
  });
});
