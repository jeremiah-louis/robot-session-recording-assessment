import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs.toFixed(0)}s`;
}

export function statusVariant(
  status: string,
): "success" | "warning" | "destructive" {
  switch (status) {
    case "completed":
      return "success";
    case "recording":
      return "warning";
    default:
      return "destructive";
  }
}

export function outcomeVariant(
  outcome: string,
): "success" | "destructive" {
  return outcome === "success" ? "success" : "destructive";
}

export function sessionDisplayName(
  sessionId: string,
  episodeIndex?: number | null,
  truncate = 8,
): string {
  if (episodeIndex != null) return `Episode ${episodeIndex}`;
  return sessionId.slice(0, truncate);
}
