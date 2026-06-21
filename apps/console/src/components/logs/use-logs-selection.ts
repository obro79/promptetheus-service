"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import type { TraceEvent } from "@/lib/types";
import {
  allExpandable,
  buildTraceTree,
  firstFailedEvent,
  pickDefaultRun,
  type LogRun,
} from "./model";

export type LogDetailTab = "run" | "feedback" | "metadata";

export interface UseLogsSelectionOptions {
  runs: LogRun[];
  filteredRuns: LogRun[];
  traceScrollRef: React.RefObject<HTMLElement | null>;
  runRowRefs: React.MutableRefObject<Map<string, HTMLTableRowElement>>;
}

function scrollIntoViewIfSupported(element: Element | undefined | null) {
  if (element && typeof element.scrollIntoView === "function") {
    element.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

export function useLogsSelection({
  runs,
  filteredRuns,
  traceScrollRef,
  runRowRefs,
}: UseLogsSelectionOptions) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [hydrated, setHydrated] = React.useState(false);
  const skipAutoDrillRef = React.useRef(true);
  const pendingScrollSeqRef = React.useRef<number | null>(null);

  const [selectedAgentId, setSelectedAgentId] = React.useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = React.useState("");
  const [selectedSeq, setSelectedSeq] = React.useState<number | null>(null);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [detailTab, setDetailTab] = React.useState<LogDetailTab>("run");
  const [traceExpanded, setTraceExpanded] = React.useState(false);

  const drillIntoRun = React.useCallback((run: LogRun, seq?: number | null) => {
    const focusEvent =
      seq != null
        ? (run.events.find((event) => event.seq === seq) ?? firstFailedEvent(run))
        : firstFailedEvent(run);
    const tree = buildTraceTree(run.events);
    setExpanded(allExpandable(tree));
    setSelectedSeq(focusEvent?.seq ?? null);
    pendingScrollSeqRef.current = focusEvent?.seq ?? null;
    setDetailTab("run");
  }, []);

  React.useEffect(() => {
    const agent = searchParams.get("agent");
    const session = searchParams.get("session");
    const seqParam = searchParams.get("seq");
    skipAutoDrillRef.current = true;

    if (session) {
      const run = runs.find((candidate) => candidate.session.id === session);
      if (run) {
        setSelectedRunId(session);
        setSelectedAgentId(agent ?? run.session.project_id);
        const seq =
          seqParam != null && Number.isFinite(Number(seqParam)) ? Number(seqParam) : null;
        drillIntoRun(run, seq);
        setTraceExpanded(true);
      }
    } else if (agent) {
      setSelectedAgentId(agent);
      const agentRuns = runs.filter((candidate) => candidate.session.project_id === agent);
      const defaultRun = pickDefaultRun(agentRuns);
      if (defaultRun) {
        setSelectedRunId(defaultRun.session.id);
        drillIntoRun(defaultRun);
      }
    } else {
      const defaultRun = pickDefaultRun(filteredRuns);
      if (defaultRun) {
        setSelectedRunId(defaultRun.session.id);
        drillIntoRun(defaultRun);
      }
    }

    setHydrated(true);
    requestAnimationFrame(() => {
      skipAutoDrillRef.current = false;
    });
    // Hydrate once from URL on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (!hydrated) return;
    const params = new URLSearchParams();
    if (selectedAgentId) params.set("agent", selectedAgentId);
    if (selectedRunId) params.set("session", selectedRunId);
    if (selectedSeq != null) params.set("seq", String(selectedSeq));
    const next = params.toString();
    const current = searchParams.toString();
    if (next !== current) {
      router.replace(next ? `/logs?${next}` : "/logs", { scroll: false });
    }
  }, [hydrated, router, searchParams, selectedAgentId, selectedRunId, selectedSeq]);

  React.useEffect(() => {
    if (skipAutoDrillRef.current) return;
    if (filteredRuns.length === 0) {
      setSelectedRunId("");
      return;
    }
    if (!filteredRuns.some((run) => run.session.id === selectedRunId)) {
      const fallback = pickDefaultRun(filteredRuns);
      if (fallback) {
        setSelectedRunId(fallback.session.id);
        drillIntoRun(fallback);
      }
    }
  }, [drillIntoRun, filteredRuns, selectedRunId]);

  React.useEffect(() => {
    if (!selectedRunId) return;

    scrollIntoViewIfSupported(runRowRefs.current.get(selectedRunId));

    const seq = pendingScrollSeqRef.current ?? selectedSeq;
    if (seq == null) return;
    requestAnimationFrame(() => {
      const container = traceScrollRef.current;
      const target = container?.querySelector(`[data-trace-seq="${seq}"]`);
      scrollIntoViewIfSupported(target);
      pendingScrollSeqRef.current = null;
    });
  }, [runRowRefs, selectedRunId, selectedSeq, traceScrollRef]);

  const prevAgentRef = React.useRef<string | null | undefined>(undefined);
  React.useEffect(() => {
    if (!hydrated) return;
    if (skipAutoDrillRef.current) {
      prevAgentRef.current = selectedAgentId;
      return;
    }
    if (prevAgentRef.current === selectedAgentId) return;
    prevAgentRef.current = selectedAgentId;

    const agentRuns = selectedAgentId
      ? filteredRuns.filter((run) => run.session.project_id === selectedAgentId)
      : filteredRuns;
    const defaultRun = pickDefaultRun(agentRuns);
    if (defaultRun) {
      setSelectedRunId(defaultRun.session.id);
      drillIntoRun(defaultRun);
    }
  }, [drillIntoRun, filteredRuns, hydrated, selectedAgentId]);

  const selectAgent = React.useCallback((agentId: string | null) => {
    setSelectedAgentId(agentId);
  }, []);

  const selectRun = React.useCallback(
    (run: LogRun) => {
      setSelectedRunId(run.session.id);
      drillIntoRun(run);
    },
    [drillIntoRun],
  );

  const selectEvent = React.useCallback((event: TraceEvent) => {
    setSelectedSeq(event.seq);
    setDetailTab("run");
  }, []);

  const selectedRun = React.useMemo(
    () => runs.find((run) => run.session.id === selectedRunId) ?? filteredRuns[0] ?? runs[0],
    [filteredRuns, runs, selectedRunId],
  );

  const selectedEvent = React.useMemo(
    () =>
      selectedRun?.events.find((event) => event.seq === selectedSeq) ??
      (selectedRun ? firstFailedEvent(selectedRun) : undefined),
    [selectedRun, selectedSeq],
  );

  return {
    hydrated,
    selectedAgentId,
    selectedRunId,
    selectedRun,
    selectedSeq,
    selectedEvent,
    expanded,
    setExpanded,
    detailTab,
    setDetailTab,
    traceExpanded,
    setTraceExpanded,
    selectAgent,
    selectRun,
    selectEvent,
  };
}
