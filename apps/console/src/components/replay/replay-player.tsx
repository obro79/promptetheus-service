"use client";

import * as React from "react";
import {
  Maximize2,
  Pause,
  Play,
  RotateCcw,
  Video as VideoIcon,
} from "lucide-react";

import type { ReplayArtifact } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ReplayPlayerProps {
  artifact: ReplayArtifact | undefined;
  /** current playback offset in seconds (controlled). */
  currentTime: number;
  /** total media duration in seconds. */
  duration: number;
  /** label for the active critical step, shown as an overlay chip. */
  criticalLabel?: string | null;
  /** true when the current time is at/after the critical step. */
  atCritical?: boolean;
  onSeek: (seconds: number) => void;
}

function fmtClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

export function ReplayPlayer({
  artifact,
  currentTime,
  duration,
  criticalLabel,
  atCritical = false,
  onSeek,
}: ReplayPlayerProps) {
  const [playing, setPlaying] = React.useState(false);
  const rafRef = React.useRef<number | null>(null);
  const lastTickRef = React.useRef<number | null>(null);

  // Drive currentTime forward while playing. The mp4 is a placeholder, so we
  // simulate playback with a timer across duration_s and surface seeks back up.
  React.useEffect(() => {
    if (!playing) {
      lastTickRef.current = null;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      return;
    }

    const tick = (now: number) => {
      if (lastTickRef.current === null) lastTickRef.current = now;
      const delta = (now - lastTickRef.current) / 1000;
      lastTickRef.current = now;
      const next = currentTime + delta;
      if (next >= duration) {
        onSeek(duration);
        setPlaying(false);
        return;
      }
      onSeek(next);
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    };
    // currentTime intentionally excluded: the rAF loop reads the latest value
    // through the closure refresh below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, currentTime, duration, onSeek]);

  const atEnd = duration > 0 && currentTime >= duration;

  const toggle = React.useCallback(() => {
    if (atEnd) {
      onSeek(0);
      setPlaying(true);
      return;
    }
    setPlaying((p) => !p);
  }, [atEnd, onSeek]);

  const restart = React.useCallback(() => {
    onSeek(0);
    setPlaying(true);
  }, [onSeek]);

  const handleScrub = React.useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onSeek(Number(e.target.value));
    },
    [onSeek],
  );

  const progress = duration > 0 ? Math.min(1, currentTime / duration) : 0;

  return (
    <div className="surface flex flex-col overflow-hidden rounded-2xl">
      {/* viewport */}
      <div className="group relative aspect-video w-full overflow-hidden bg-canvas">
        {/* placeholder "frame": violet-tinted grid + glow */}
        <div className="absolute inset-0 grid-fade opacity-50" />
        <div
          className={cn(
            "absolute inset-0 bg-gradient-to-br transition-colors duration-500",
            atCritical
              ? "from-destructive/10 via-canvas to-canvas"
              : "from-accent/10 via-canvas to-canvas",
          )}
        />
        <div
          className={cn(
            "pointer-events-none absolute -inset-x-12 -top-24 h-48 blur-3xl transition-opacity duration-500",
            atCritical ? "bg-destructive/10" : "bg-accent/10",
          )}
        />

        {/* center play affordance */}
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? "Pause replay" : "Play replay"}
          className="absolute inset-0 flex flex-col items-center justify-center gap-3 outline-none"
        >
          <span
            className={cn(
              "flex size-16 items-center justify-center rounded-full border backdrop-blur-sm transition-all duration-150",
              "border-accent/40 bg-accent/10 text-accent",
              "group-hover:scale-105 group-hover:border-accent/60 group-hover:bg-accent/20",
            )}
          >
            {playing ? (
              <Pause className="size-6" />
            ) : (
              <Play className="size-6 translate-x-0.5" />
            )}
          </span>
          <span className="mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {artifact ? "Session replay" : "No recording"}
          </span>
        </button>

        {/* top-left source chip */}
        <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-1.5 rounded-md border border-border/80 bg-canvas/70 px-2 py-1 backdrop-blur-sm">
          <VideoIcon className="size-3 text-accent" />
          <span className="mono truncate text-[11px] text-muted-foreground">
            {artifact ? artifact.storage_path : "—"}
          </span>
        </div>

        {/* critical overlay chip */}
        {atCritical && criticalLabel ? (
          <div className="pointer-events-none absolute right-3 top-3 flex items-center gap-1.5 rounded-md border border-destructive/40 bg-destructive/15 px-2 py-1 backdrop-blur-sm">
            <span className="relative flex size-1.5">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-destructive opacity-60" />
              <span className="relative inline-flex size-1.5 rounded-full bg-destructive" />
            </span>
            <span className="mono text-[11px] font-medium text-destructive">
              {criticalLabel}
            </span>
          </div>
        ) : null}

        {/* live clock */}
        <div className="pointer-events-none absolute bottom-3 right-3 rounded-md border border-border/80 bg-canvas/70 px-2 py-1 backdrop-blur-sm">
          <span className="mono text-[11px] tabular-nums text-foreground">
            {fmtClock(currentTime)}
            <span className="text-muted-foreground/60"> / {fmtClock(duration)}</span>
          </span>
        </div>
      </div>

      {/* transport bar */}
      <div className="flex items-center gap-3 border-t border-border px-3 py-2.5">
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? "Pause" : "Play"}
          className="flex size-7 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground transition-colors duration-150 hover:bg-accent/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {playing ? (
            <Pause className="size-3.5" />
          ) : (
            <Play className="size-3.5 translate-x-px" />
          )}
        </button>
        <button
          type="button"
          onClick={restart}
          aria-label="Restart"
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <RotateCcw className="size-3.5" />
        </button>

        {/* native scrub track styled with progress fill */}
        <div className="relative flex h-7 flex-1 items-center">
          <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${progress * 100}%` }}
            />
          </div>
          <input
            type="range"
            min={0}
            max={duration || 1}
            step={0.05}
            value={currentTime}
            onChange={handleScrub}
            aria-label="Seek replay"
            className="relative z-10 h-7 w-full cursor-pointer appearance-none bg-transparent outline-none [&::-webkit-slider-thumb]:size-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow [&::-webkit-slider-thumb]:ring-2 [&::-webkit-slider-thumb]:ring-canvas [&::-moz-range-thumb]:size-3 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-accent"
          />
        </div>

        <span className="mono shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {fmtClock(currentTime)} / {fmtClock(duration)}
        </span>

        <button
          type="button"
          aria-label="Fullscreen"
          disabled
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/40"
        >
          <Maximize2 className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
