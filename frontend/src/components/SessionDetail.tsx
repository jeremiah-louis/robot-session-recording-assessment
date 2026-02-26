import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, type Session, type TopicSummary, type SearchResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TimelineSeek } from "@/components/TimelineSeek";
import {
  formatDuration,
  outcomeVariant,
  sessionDisplayName,
  statusVariant,
} from "@/lib/utils";
import {
  ArrowLeft,
  Download,
  Activity,
  Cpu,
  Clock,
  BarChart3,
} from "lucide-react";

export function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [session, setSession] = useState<Session | null>(null);
  const [topics, setTopics] = useState<TopicSummary[]>([]);
  const [similar, setSimilar] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      api.getSession(id),
      api.getTopics(id),
      api.getSimilar(id, 5).catch(() => []),
    ]).then(([s, t, sim]) => {
      setSession(s);
      setTopics(t);
      setSimilar(sim);
      setLoading(false);
    });
  }, [id]);

  if (loading || !session) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const duration = session.end_time
    ? session.end_time - session.start_time
    : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate("/sessions")}
            className="h-8 w-8"
          >
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div>
            <h2 className="flex items-center gap-2">
              {sessionDisplayName(session.session_id, session.episode_index, 12)}
              <Badge variant={statusVariant(session.status)}>
                {session.status}
              </Badge>
              {session.outcome && (
                <Badge variant={outcomeVariant(session.outcome)}>
                  {session.outcome}
                </Badge>
              )}
            </h2>
            {session.task && (
              <p className="text-sm text-muted-foreground mt-1">
                {session.task}
              </p>
            )}
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          asChild
        >
          <a href={api.getExportUrl(session.session_id)} download>
            <Download className="w-3.5 h-3.5 mr-1.5" />
            Export
          </a>
        </Button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          {
            icon: Clock,
            label: "Duration",
            value: formatDuration(duration),
          },
          {
            icon: BarChart3,
            label: "Frames",
            value: session.total_frames.toLocaleString(),
          },
          {
            icon: Activity,
            label: "FPS",
            value: session.fps?.toFixed(0) ?? "--",
          },
          {
            icon: Cpu,
            label: "Reward",
            value:
              session.total_reward != null
                ? session.total_reward.toFixed(1)
                : "--",
          },
        ].map((stat) => (
          <div
            key={stat.label}
            className="border border-border rounded-lg p-3 bg-card"
          >
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <stat.icon className="w-3.5 h-3.5" />
              <span className="text-xs">{stat.label}</span>
            </div>
            <p className="text-lg font-mono font-medium">{stat.value}</p>
          </div>
        ))}
      </div>

      {session.summary && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
            Text Summary
          </h4>
          <p className="text-sm leading-relaxed">{session.summary}</p>
        </div>
      )}

      <Tabs defaultValue="timeline">
        <TabsList>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="topics">Topics</TabsTrigger>
          <TabsTrigger value="similar">Similar</TabsTrigger>
          <TabsTrigger value="meta">Metadata</TabsTrigger>
        </TabsList>

        <TabsContent value="timeline">
          {duration > 0 ? (
            <TimelineSeek
              sessionId={session.session_id}
              topics={topics}
              duration={duration}
            />
          ) : (
            <p className="text-sm text-muted-foreground py-8 text-center">
              No timeline data (session still recording or no duration)
            </p>
          )}
        </TabsContent>

        <TabsContent value="topics">
          <div className="border border-border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">
                    Topic
                  </th>
                  <th className="text-right px-4 py-2 font-medium text-muted-foreground">
                    Messages
                  </th>
                  <th className="text-right px-4 py-2 font-medium text-muted-foreground">
                    Frequency
                  </th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">
                    Type
                  </th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">
                    Time Range
                  </th>
                </tr>
              </thead>
              <tbody>
                {topics.map((t) => (
                  <tr
                    key={t.topic}
                    className="border-b border-border"
                  >
                    <td className="px-4 py-2 font-mono text-xs">
                      {t.topic}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {t.message_count}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {t.avg_frequency
                        ? `${t.avg_frequency.toFixed(1)} Hz`
                        : "--"}
                    </td>
                    <td className="px-4 py-2">
                      <Badge variant="outline">{t.data_type}</Badge>
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                      {t.first_time.toFixed(1)}s — {t.last_time.toFixed(1)}s
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="similar">
          {similar.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              No similar sessions found (embeddings may not be generated yet)
            </p>
          ) : (
            <div className="space-y-2">
              {similar.map((r) => (
                <div
                  key={r.session.session_id}
                  className="flex items-center justify-between border border-border rounded-lg p-3 hover:bg-muted/30 cursor-pointer transition-colors"
                  onClick={() =>
                    navigate(`/sessions/${r.session.session_id}`)
                  }
                >
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs">
                      {sessionDisplayName(r.session.session_id, r.session.episode_index)}
                    </span>
                    {r.session.outcome && (
                      <Badge variant={outcomeVariant(r.session.outcome)}>
                        {r.session.outcome}
                      </Badge>
                    )}
                  </div>
                  <span className="text-xs font-mono text-muted-foreground">
                    {(r.score * 100).toFixed(1)}% match
                  </span>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="meta">
          <div className="border border-border rounded-lg p-4 bg-card">
            <dl className="grid grid-cols-2 gap-3 text-sm">
              {[
                ["Session ID", session.session_id],
                ["Source", session.source],
                ["Dataset", session.dataset_name ?? "--"],
                ["Robot Type", session.robot_type ?? "--"],
                ["FPS", session.fps?.toString() ?? "--"],
                ["Start Time", session.start_time.toFixed(3)],
                ["End Time", session.end_time?.toFixed(3) ?? "--"],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-muted-foreground text-xs">{label}</dt>
                  <dd className="font-mono text-xs mt-0.5">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
