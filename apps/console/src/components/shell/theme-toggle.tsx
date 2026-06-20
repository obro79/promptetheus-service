"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";

type Theme = "dark" | "light";

const STORAGE_KEY = "promptetheus.theme";

export function ThemeToggle() {
  const [theme, setTheme] = React.useState<Theme>("light");

  React.useEffect(() => {
    setTheme(document.documentElement.classList.contains("light") ? "light" : "dark");
  }, []);

  const nextTheme = theme === "dark" ? "light" : "dark";
  const label = `Switch to ${nextTheme} mode`;

  function toggleTheme() {
    const root = document.documentElement;
    root.classList.toggle("light", nextTheme === "light");
    root.classList.toggle("dark", nextTheme === "dark");
    setTheme(nextTheme);
    try {
      window.localStorage.setItem(STORAGE_KEY, nextTheme);
    } catch {}
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-11 rounded-lg"
      aria-label={label}
      title={label}
      onClick={toggleTheme}
    >
      {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  );
}
