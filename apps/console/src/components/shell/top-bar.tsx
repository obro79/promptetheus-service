"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  AlertTriangle,
  Bot,
  ChevronRight,
  Database,
  ListTree,
  Search,
  Server,
  type LucideIcon,
} from "lucide-react";

import { Kbd } from "@/components/ui/kbd";
import { CommandPalette } from "@/components/shell/command-palette";
import { ConnectionStatus } from "@/components/shell/connection-status";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { getProjects } from "@/lib/data";
import { cn, shortId } from "@/lib/utils";

const LABELS: Record<string, string> = {
  demo: "Demo",
  sessions: "Sessions",
  incidents: "Incidents",
  agents: "Agents",
  docs: "API Docs",
  settings: "Settings",
  projects: "Projects",
};

const COMPACT_NAV: Array<{ href: string; label: string; Icon: LucideIcon }> = [
  { href: "/incidents", label: "Incidents", Icon: AlertTriangle },
  { href: "/sessions", label: "Sessions", Icon: ListTree },
  { href: "/agents", label: "Agents", Icon: Bot },
];

export function TopBar() {
  const pathname = usePathname();
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const projects = getProjects();
  const segments = pathname.split("/").filter(Boolean);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <>
      <header className="z-30 flex h-16 shrink-0 items-center gap-2 border-b border-border/45 bg-panel/72 px-2.5 shadow-depth backdrop-blur-xl sm:px-4">
        <nav className="hidden min-w-0 items-center gap-1 text-[11px] uppercase tracking-[0.18em] lg:flex" aria-label="Breadcrumb">
          {segments.length === 0 ? <span className="font-medium">Incidents</span> : null}
          {segments.map((segment, index) => {
            const href = `/${segments.slice(0, index + 1).join("/")}`;
            const last = index === segments.length - 1;
            const label = LABELS[segment] ?? shortId(segment, 12);
            return (
              <React.Fragment key={href}>
                {index > 0 ? <ChevronRight className="size-3 text-muted-foreground/50" /> : null}
                {last ? (
                  <span className="mono truncate text-foreground">{label}</span>
                ) : (
                  <Link href={href} className="text-muted-foreground transition-colors hover:text-foreground">
                    {label}
                  </Link>
                )}
              </React.Fragment>
            );
          })}
        </nav>

        <Link
          href="/incidents"
          aria-label="Promptetheus home"
          className="flex size-11 shrink-0 items-center justify-center rounded-full border border-border/70 bg-panel/80 text-xs font-bold text-accent shadow-glow-sm lg:hidden"
        >
          P
        </Link>

        <nav className="flex min-w-0 items-center gap-0.5 lg:hidden" aria-label="Primary navigation">
          {COMPACT_NAV.map(({ href, label, Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                aria-label={label}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex min-h-11 min-w-10 items-center justify-center gap-1.5 rounded-full px-2 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "border border-accent/30 bg-accent-muted text-accent"
                    : "text-muted-foreground hover:bg-elevated/70 hover:text-foreground",
                )}
              >
                <Icon className="size-3.5 shrink-0" strokeWidth={1.7} />
                <span className="hidden min-[460px]:inline">{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto hidden items-center gap-1.5 xl:flex">
          <ContextChip Icon={Database} label={projects[0]?.name ?? "Project"} />
          <ContextChip Icon={Server} label="production" />
          <ContextChip Icon={Bot} label="all agents" />
        </div>

        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className="hidden min-h-10 w-48 items-center gap-2 rounded-full border border-border/70 bg-panel/70 px-3 text-xs text-muted-foreground shadow-sm transition-colors hover:border-border-strong hover:bg-panel hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:flex"
        >
          <Search className="size-3.5" />
          <span>Search</span>
          <span className="ml-auto flex gap-0.5"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
        </button>
        <ThemeToggle />
        <ConnectionStatus />
      </header>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </>
  );
}

function ContextChip({ Icon, label }: { Icon: React.ComponentType<{ className?: string }>; label: string }) {
  return (
    <span className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-border/55 bg-panel/60 px-3 text-[11px] text-muted-foreground">
      <Icon className="size-3" />
      {label}
    </span>
  );
}
