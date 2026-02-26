import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, type Session } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatDuration,
  outcomeVariant,
  sessionDisplayName,
  statusVariant,
} from "@/lib/utils";
import { Activity, Database, ChevronLeft, ChevronRight } from "lucide-react";

const PAGE_SIZE = 25;

export function SessionList() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const sourceFilter = searchParams.get("source") || "";
  const page = Number(searchParams.get("page") || "0");

  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .listSessions(sourceFilter || undefined, PAGE_SIZE, page * PAGE_SIZE)
      .then((res) => {
        setSessions(res.sessions);
        setTotal(res.total);
      })
      .finally(() => setLoading(false));
  }, [sourceFilter, page]);

  const setFilter = (source: string) => {
    const p = new URLSearchParams(searchParams);
    if (source) p.set("source", source);
    else p.delete("source");
    p.delete("page");
    setSearchParams(p);
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2>Sessions</h2>
          <p className="text-sm text-muted-foreground mt-1">
            {total} sessions recorded
          </p>
        </div>
        <div className="flex gap-2">
          {["", "live", "import"].map((s) => (
            <Button
              key={s}
              variant={sourceFilter === s ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter(s)}
            >
              {s === "" ? "All" : s === "live" ? "Live" : "Imported"}
            </Button>
          ))}
        </div>
      </div>

      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/50">
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                Session
              </th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                Source
              </th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                Status
              </th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                Outcome
              </th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                Duration
              </th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                Frames
              </th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                Reward
              </th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                Created
              </th>
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-border">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <Skeleton className="h-4 w-20" />
                      </td>
                    ))}
                  </tr>
                ))
              : sessions.map((s) => (
                  <tr
                    key={s.session_id}
                    className="border-b border-border hover:bg-muted/30 cursor-pointer transition-colors"
                    onClick={() => navigate(`/sessions/${s.session_id}`)}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {s.source === "live" ? (
                          <Activity className="w-3.5 h-3.5 text-chart-1" />
                        ) : (
                          <Database className="w-3.5 h-3.5 text-chart-3" />
                        )}
                        <span className="font-mono text-xs">
                          {sessionDisplayName(s.session_id, s.episode_index)}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant={
                          s.source === "live" ? "secondary" : "outline"
                        }
                      >
                        {s.source}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={statusVariant(s.status)}>
                        {s.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {s.outcome ? (
                        <Badge variant={outcomeVariant(s.outcome)}>
                          {s.outcome}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">--</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {s.end_time
                        ? formatDuration(s.end_time - s.start_time)
                        : "--"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {s.total_frames}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {s.total_reward != null
                        ? s.total_reward.toFixed(1)
                        : "--"}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {s.created_at
                        ? new Date(s.created_at).toLocaleDateString()
                        : "--"}
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            Page {page + 1} of {totalPages}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => {
                const p = new URLSearchParams(searchParams);
                p.set("page", String(page - 1));
                setSearchParams(p);
              }}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages - 1}
              onClick={() => {
                const p = new URLSearchParams(searchParams);
                p.set("page", String(page + 1));
                setSearchParams(p);
              }}
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
