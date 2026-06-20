"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  AlertTriangle,
  BookOpen,
  Bot,
  Check,
  ChevronsUpDown,
  FlaskConical,
  ListTree,
  Settings,
  type LucideIcon,
} from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ConnectionStatus } from "@/components/shell/connection-status";
import { getProjects, getWorkspace } from "@/lib/data";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  Icon: LucideIcon;
}

const PRIMARY_NAV: NavItem[] = [
  { label: "Incidents", href: "/incidents", Icon: AlertTriangle },
  { label: "Sessions", href: "/sessions", Icon: ListTree },
  { label: "Agents", href: "/agents", Icon: Bot },
];

const UTILITY_NAV: NavItem[] = [
  { label: "Demo", href: "/demo", Icon: FlaskConical },
  { label: "API Docs", href: "/docs", Icon: BookOpen },
  { label: "Settings", href: "/settings/projects", Icon: Settings },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/settings/projects") return pathname.startsWith("/settings");
  return pathname === href || pathname.startsWith(`${href}/`);
}

function isConsolePath(pathname: string): boolean {
  return /^\/(sessions|incidents)\/[^/]+/.test(pathname) || pathname === "/demo";
}

export function AppSidebar() {
  const pathname = usePathname();
  const workspace = getWorkspace();
  const projects = getProjects();
  const [activeProject, setActiveProject] = React.useState(projects[0]);
  const compact = isConsolePath(pathname);

  return (
    <aside
      className={cn(
        "hidden h-dvh shrink-0 flex-col border-r border-border/50 bg-panel/78 shadow-depth backdrop-blur-xl lg:flex",
        compact ? "w-16" : "w-60",
      )}
      aria-label="Workspace navigation"
    >
      <div className={cn("border-b border-border/45", compact ? "p-2.5" : "p-4")}>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={`Switch project. Current project: ${activeProject?.name ?? "none"}`}
              className={cn(
                "group flex min-h-11 w-full items-center rounded-full text-left transition-colors hover:bg-elevated/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                compact ? "justify-center px-1" : "gap-3 px-2",
              )}
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-accent/25 bg-accent-muted text-[12px] font-semibold text-accent shadow-glow-sm">
                P
              </span>
              {!compact ? (
                <>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="display truncate text-[19px] leading-none text-foreground">
                      Promptetheus
                    </span>
                    <span className="mono mt-1 truncate text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                      {activeProject?.name ?? workspace.name}
                    </span>
                  </span>
                  <ChevronsUpDown className="size-3.5 text-muted-foreground" />
                </>
              ) : null}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56" sideOffset={6}>
            <DropdownMenuLabel>{workspace.name}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {projects.map((project) => (
              <DropdownMenuItem
                key={project.id}
                onSelect={() => setActiveProject(project)}
                className="flex items-center gap-2"
              >
                <span className="flex size-5 items-center justify-center rounded-md bg-elevated text-[10px]">
                  {project.name.charAt(0)}
                </span>
                <span className="truncate">{project.name}</span>
                {activeProject?.id === project.id ? (
                  <Check className="ml-auto size-3.5 text-accent" />
                ) : null}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <NavGroup items={PRIMARY_NAV} pathname={pathname} compact={compact} className="pt-4" />
      <div className="mx-4 my-4 border-t border-border/45" />
      <NavGroup items={UTILITY_NAV} pathname={pathname} compact={compact} />

      <div className={cn("mt-auto border-t border-border/45", compact ? "p-2.5" : "p-4")}>
        <div className={cn("flex min-h-11 items-center rounded-full", compact ? "justify-center" : "gap-2.5 border border-border/50 bg-panel/55 px-2")}>
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-elevated text-[10px] font-semibold text-accent">
            OF
          </span>
          {!compact ? (
            <>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-[12px] font-medium text-foreground">Owen Fisher</span>
                <span className="truncate text-[10px] text-muted-foreground">owen@acme.com</span>
              </span>
              <ConnectionStatus compact />
            </>
          ) : null}
        </div>
      </div>
    </aside>
  );
}

function NavGroup({
  items,
  pathname,
  compact,
  className,
}: {
  items: NavItem[];
  pathname: string;
  compact: boolean;
  className?: string;
}) {
  return (
    <nav className={cn("space-y-1.5 px-2.5", className)}>
      {items.map(({ label, href, Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            title={compact ? label : undefined}
            aria-label={compact ? label : undefined}
            className={cn(
              "relative flex min-h-10 items-center rounded-full text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              compact ? "justify-center px-1" : "gap-2.5 px-3",
              active
                ? "border border-accent/25 bg-accent-muted text-accent shadow-glow-sm"
                : "text-muted-foreground hover:bg-elevated/70 hover:text-foreground",
            )}
          >
            <Icon className={cn("size-4 shrink-0", active && "text-accent")} strokeWidth={1.5} />
            {!compact ? label : null}
          </Link>
        );
      })}
    </nav>
  );
}
