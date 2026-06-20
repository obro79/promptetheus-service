"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  BookOpen,
  Home,
  ListTree,
  PlayCircle,
  Settings,
} from "lucide-react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { SeverityBadge } from "@/components/common/severity-badge";
import { StatusPill } from "@/components/common/status-pill";
import { getIncidents, getSessions } from "@/lib/data";
import { shortId } from "@/lib/utils";

const NAV = [
  { label: "Home", href: "/", Icon: Home },
  { label: "Demo", href: "/demo", Icon: PlayCircle },
  { label: "Sessions", href: "/sessions", Icon: ListTree },
  { label: "Incidents", href: "/incidents", Icon: AlertTriangle },
  { label: "API Docs", href: "/docs", Icon: BookOpen },
  { label: "Settings", href: "/settings/projects", Icon: Settings },
] as const;

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter();
  const sessions = React.useMemo(() => getSessions().slice(0, 6), []);
  const incidents = React.useMemo(() => getIncidents().slice(0, 6), []);

  const go = React.useCallback(
    (href: string) => {
      onOpenChange(false);
      router.push(href);
    },
    [onOpenChange, router],
  );

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Search sessions, incidents, or jump to a page…" />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Navigate">
          {NAV.map(({ label, href, Icon }) => (
            <CommandItem
              key={href}
              value={`nav ${label}`}
              onSelect={() => go(href)}
            >
              <Icon className="text-muted-foreground" />
              <span>{label}</span>
            </CommandItem>
          ))}
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Recent sessions">
          {sessions.map((s) => (
            <CommandItem
              key={s.id}
              value={`session ${s.id} ${s.user_goal ?? ""}`}
              onSelect={() => go(`/sessions/${s.id}`)}
            >
              <ListTree className="text-muted-foreground" />
              <span className="truncate">
                {s.user_goal ?? "Untitled session"}
              </span>
              <span className="mono ml-auto pl-3 text-[10px] text-muted-foreground/70">
                {shortId(s.id, 10)}
              </span>
              <StatusPill status={s.status} className="ml-2 shrink-0" />
            </CommandItem>
          ))}
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Open incidents">
          {incidents.map((i) => (
            <CommandItem
              key={i.id}
              value={`incident ${i.id} ${i.title}`}
              onSelect={() => go(`/incidents/${i.id}`)}
            >
              <AlertTriangle className="text-muted-foreground" />
              <span className="truncate">{i.title}</span>
              <SeverityBadge
                severity={i.severity}
                showIcon={false}
                className="ml-auto shrink-0"
              />
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
