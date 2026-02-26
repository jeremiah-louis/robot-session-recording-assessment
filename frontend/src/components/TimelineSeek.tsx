import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Message, type TopicSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Play, Pause } from "lucide-react";

interface ParsedPoint {
  t: number;
  vals: number[];
}

/** Buffer multiplier -- fetch 3x the visible window so playback has headroom */
const BUFFER_MULT = 3;
/** Re-fetch when visible edge is within this fraction of buffer edge */
const REFETCH_THRESHOLD = 0.25;

const PLOT_COLORS = [
  "oklch(0.75 0.15 160)",
  "oklch(0.70 0.12 200)",
  "oklch(0.65 0.18 280)",
  "oklch(0.80 0.15 80)",
  "oklch(0.60 0.20 30)",
  "oklch(0.75 0.10 320)",
];

const GRID_DIVISIONS = 4;

const CHART_PADDING = { top: 16, right: 16, bottom: 28, left: 48 };

const WINDOW_PRESETS = [2, 5, 10];

// -- Helpers ------------------------------------------------------------------

function parseMessageData(m: Message): number[] | null {
  if (!m.data) return null;
  if (Array.isArray(m.data)) return m.data as number[];
  if (typeof m.data === "string") {
    try {
      const parsed = JSON.parse(m.data);
      return Array.isArray(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }
  return null;
}

function groupMessages(msgs: Message[]): Record<string, ParsedPoint[]> {
  const grouped: Record<string, ParsedPoint[]> = {};
  for (const m of msgs) {
    const vals = parseMessageData(m);
    if (!vals) continue;
    (grouped[m.topic] ??= []).push({ t: m.timestamp, vals });
  }
  for (const pts of Object.values(grouped)) {
    pts.sort((a, b) => a.t - b.t);
  }
  return grouped;
}

function filterVisiblePoints(
  grouped: Record<string, ParsedPoint[]>,
  tMin: number,
  tMax: number,
): { visible: Record<string, ParsedPoint[]>; hasData: boolean } {
  const margin = (tMax - tMin) * 0.02;
  const visible: Record<string, ParsedPoint[]> = {};
  let hasData = false;

  for (const [topic, pts] of Object.entries(grouped)) {
    const filtered = pts.filter(
      (p) => p.t >= tMin - margin && p.t <= tMax + margin,
    );
    if (filtered.length > 0) {
      visible[topic] = filtered;
      hasData = true;
    }
  }

  return { visible, hasData };
}

function computeYBounds(visible: Record<string, ParsedPoint[]>): {
  min: number;
  max: number;
} {
  let gMin = Infinity;
  let gMax = -Infinity;

  for (const pts of Object.values(visible)) {
    for (const p of pts) {
      for (const v of p.vals) {
        if (typeof v !== "number" || !isFinite(v)) continue;
        if (v < gMin) gMin = v;
        if (v > gMax) gMax = v;
      }
    }
  }

  if (!isFinite(gMin) || !isFinite(gMax)) return { min: -1, max: 1 };
  if (gMin === gMax) return { min: gMin - 1, max: gMax + 1 };
  return { min: gMin, max: gMax };
}

function drawChart(
  canvas: HTMLCanvasElement,
  grouped: Record<string, ParsedPoint[]>,
  tMin: number,
  tMax: number,
): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  const plotW = w - CHART_PADDING.left - CHART_PADDING.right;
  const plotH = h - CHART_PADDING.top - CHART_PADDING.bottom;

  ctx.clearRect(0, 0, w, h);

  const { visible, hasData } = filterVisiblePoints(grouped, tMin, tMax);
  const yBounds = computeYBounds(visible);

  const scaleX = (t: number): number =>
    CHART_PADDING.left + ((t - tMin) / (tMax - tMin)) * plotW;
  const scaleY = (v: number): number =>
    CHART_PADDING.top + plotH - ((v - yBounds.min) / (yBounds.max - yBounds.min)) * plotH;

  drawGrid(ctx, w, h, plotW, plotH);
  drawAxisLabels(ctx, h, plotW, plotH, tMin, tMax, yBounds);

  if (!hasData) return;

  drawDataLines(ctx, visible, plotW, plotH, scaleX, scaleY);
}

function drawGrid(
  ctx: CanvasRenderingContext2D,
  w: number,
  _h: number,
  _plotW: number,
  plotH: number,
): void {
  ctx.strokeStyle = "oklch(0.275 0 0)";
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= GRID_DIVISIONS; i++) {
    const y = CHART_PADDING.top + (plotH * i) / GRID_DIVISIONS;
    ctx.beginPath();
    ctx.moveTo(CHART_PADDING.left, y);
    ctx.lineTo(w - CHART_PADDING.right, y);
    ctx.stroke();
  }
}

function drawAxisLabels(
  ctx: CanvasRenderingContext2D,
  h: number,
  plotW: number,
  plotH: number,
  tMin: number,
  tMax: number,
  yBounds: { min: number; max: number },
): void {
  ctx.fillStyle = "oklch(0.65 0 0)";
  ctx.font = "10px 'IBM Plex Mono', monospace";

  ctx.textAlign = "right";
  for (let i = 0; i <= GRID_DIVISIONS; i++) {
    const v = yBounds.min + ((yBounds.max - yBounds.min) * (GRID_DIVISIONS - i)) / GRID_DIVISIONS;
    const y = CHART_PADDING.top + (plotH * i) / GRID_DIVISIONS + 3;
    ctx.fillText(v.toFixed(2), CHART_PADDING.left - 6, y);
  }

  ctx.textAlign = "center";
  for (let i = 0; i <= GRID_DIVISIONS; i++) {
    const t = tMin + ((tMax - tMin) * i) / GRID_DIVISIONS;
    ctx.fillText(`${t.toFixed(1)}s`, CHART_PADDING.left + (plotW * i) / GRID_DIVISIONS, h - 6);
  }
}

function drawDataLines(
  ctx: CanvasRenderingContext2D,
  visible: Record<string, ParsedPoint[]>,
  plotW: number,
  plotH: number,
  scaleX: (t: number) => number,
  scaleY: (v: number) => number,
): void {
  ctx.save();
  ctx.beginPath();
  ctx.rect(CHART_PADDING.left, CHART_PADDING.top, plotW, plotH);
  ctx.clip();

  let colorIdx = 0;
  for (const pts of Object.values(visible)) {
    if (pts.length < 2) continue;

    const dimCount = pts[0].vals.length;
    for (let d = 0; d < dimCount; d++) {
      ctx.strokeStyle = PLOT_COLORS[colorIdx % PLOT_COLORS.length];
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let i = 0; i < pts.length; i++) {
        const x = scaleX(pts[i].t);
        const y = scaleY(pts[i].vals[d]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      colorIdx++;
    }
  }

  ctx.restore();
}

// -- Component ----------------------------------------------------------------

interface Props {
  sessionId: string;
  topics: TopicSummary[];
  duration: number;
}

export function TimelineSeek({ sessionId, topics, duration }: Props) {
  const [range, setRange] = useState<[number, number]>([0, Math.min(5, duration)]);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const animRef = useRef<number | undefined>(undefined);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const bufferRef = useRef<{
    start: number;
    end: number;
    grouped: Record<string, ParsedPoint[]>;
  }>({ start: 0, end: 0, grouped: {} });
  const [bufferVersion, setBufferVersion] = useState(0);
  const fetchingRef = useRef(false);

  const numericTopics = useMemo(
    () => topics.filter((t) => t.data_type !== "image_ref"),
    [topics],
  );

  const topicNames = useMemo(
    () => numericTopics.map((t) => t.topic),
    [numericTopics],
  );

  const fetchBuffer = useCallback(
    async (visStart: number, visEnd: number) => {
      if (fetchingRef.current) return;
      fetchingRef.current = true;
      setLoading(true);

      const windowSize = visEnd - visStart;
      const bufferPad = windowSize * ((BUFFER_MULT - 1) / 2);
      const bufStart = Math.max(0, visStart - bufferPad);
      const bufEnd = Math.min(duration, visEnd + bufferPad);

      try {
        const msgs = await api.seek(sessionId, bufStart, bufEnd, topicNames, 10000);
        bufferRef.current = { start: bufStart, end: bufEnd, grouped: groupMessages(msgs) };
        setBufferVersion((v) => v + 1);
      } finally {
        fetchingRef.current = false;
        setLoading(false);
      }
    },
    [sessionId, topicNames, duration],
  );

  // Initial fetch + re-fetch when topics change
  useEffect(() => {
    fetchBuffer(range[0], range[1]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, topicNames.join(",")]);

  // Re-fetch when the visible window approaches the buffer edge
  useEffect(() => {
    const buf = bufferRef.current;
    const windowSize = range[1] - range[0];
    const threshold = windowSize * REFETCH_THRESHOLD;

    const needsFetch =
      buf.start === buf.end ||
      range[0] < buf.start + threshold ||
      range[1] > buf.end - threshold;

    if (needsFetch) {
      fetchBuffer(range[0], range[1]);
    }
  }, [range, fetchBuffer]);

  // Canvas drawing -- runs on every range change using buffered data
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    drawChart(canvas, bufferRef.current.grouped, range[0], range[1]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range, bufferVersion]);

  // Playback animation
  useEffect(() => {
    if (!playing) {
      if (animRef.current) cancelAnimationFrame(animRef.current);
      return;
    }

    let prev: number | null = null;
    function tick(now: number): void {
      if (prev !== null) {
        const dtSec = (now - prev) / 1000;
        setRange(([s, e]) => {
          const windowSize = e - s;
          const newStart = s + dtSec;
          if (newStart + windowSize > duration) {
            setPlaying(false);
            return [duration - windowSize, duration];
          }
          return [newStart, newStart + windowSize];
        });
      }
      prev = now;
      animRef.current = requestAnimationFrame(tick);
    }
    animRef.current = requestAnimationFrame(tick);

    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [playing, duration]);

  const windowSize = range[1] - range[0];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Button
          variant="outline"
          size="icon"
          onClick={() => setPlaying(!playing)}
          className="h-8 w-8"
        >
          {playing ? (
            <Pause className="w-3.5 h-3.5" />
          ) : (
            <Play className="w-3.5 h-3.5" />
          )}
        </Button>

        <div className="flex-1 space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground font-mono">
            <span>{range[0].toFixed(1)}s</span>
            <span>{range[1].toFixed(1)}s</span>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(0, duration - windowSize)}
            step={0.1}
            value={range[0]}
            onChange={(e) => {
              const start = parseFloat(e.target.value);
              setRange([start, start + windowSize]);
            }}
            className="w-full accent-primary h-1"
          />
        </div>

        <div className="flex gap-2">
          {WINDOW_PRESETS.map((w) => (
            <Button
              key={w}
              variant={windowSize === w ? "secondary" : "ghost"}
              size="sm"
              className="text-xs h-7 px-2"
              onClick={() => {
                const mid = (range[0] + range[1]) / 2;
                const start = Math.max(0, mid - w / 2);
                setRange([start, Math.min(duration, start + w)]);
              }}
            >
              {w}s
            </Button>
          ))}
        </div>
      </div>

      <div className="border border-border rounded-lg bg-card p-2 relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-card/80 rounded-lg z-10">
            <Skeleton className="h-4 w-32" />
          </div>
        )}
        <canvas
          ref={canvasRef}
          className="w-full"
          style={{ height: 220 }}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        {numericTopics.map((t) => (
          <div
            key={t.topic}
            className="text-xs font-mono px-2 py-1 rounded bg-muted text-muted-foreground"
          >
            {t.topic}
          </div>
        ))}
      </div>
    </div>
  );
}
