import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TraceEvent } from "@/lib/types";
import { EventStream } from "./event-stream";

describe("EventStream", () => {
  it("windows large traces instead of mounting every event row", () => {
    const events = Array.from({ length: 500 }, (_, seq) => ({
      type: "tool_call",
      session_id: "ses_large",
      timestamp: "2026-06-18T00:00:00Z",
      seq,
      idempotency_key: `event-${seq}`,
      t_offset_ms: seq * 100,
      payload: { tool_name: "test_tool", arguments: { seq } },
    })) as TraceEvent[];

    render(<div style={{ height: 520 }}><EventStream events={events} selectedSeq={0} criticalSeq={420} evidence={[420]} onSelect={() => undefined} /></div>);

    expect(screen.getByText("500 of 500 events")).toBeInTheDocument();
    expect(screen.getAllByRole("button").length).toBeLessThan(40);
  });
});
