import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import { api, type GraphNode } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

const OUTCOME_COLORS = {
  success: "oklch(0.72 0.18 155)",
  failure: "oklch(0.70 0.19 22)",
  unknown: "oklch(0.55 0 0)",
} as const;

const LEGEND_ITEMS = [
  { label: "Success", color: OUTCOME_COLORS.success },
  { label: "Failure", color: OUTCOME_COLORS.failure },
  { label: "Unknown", color: OUTCOME_COLORS.unknown },
] as const;

interface EnrichedNode extends GraphNode {
  __color: string;
  __size: number;
}

interface EnrichedLink {
  source: string;
  target: string;
  weight: number;
}

interface EnrichedGraphData {
  nodes: EnrichedNode[];
  links: EnrichedLink[];
}

function nodeColor(outcome?: string): string {
  if (outcome === "success") return OUTCOME_COLORS.success;
  if (outcome === "failure") return OUTCOME_COLORS.failure;
  return OUTCOME_COLORS.unknown;
}

function nodeSize(reward?: number): number {
  if (reward == null) return 4;
  return Math.max(3, Math.min(12, 3 + reward / 10));
}

export function SimilarityGraph() {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const [graphData, setGraphData] = useState<EnrichedGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    api
      .getSimilarityGraph()
      .then((data) => {
        setGraphData({
          nodes: data.nodes.map((n) => ({
            ...n,
            __color: nodeColor(n.outcome),
            __size: nodeSize(n.reward),
          })),
          links: data.edges.map((e) => ({
            source: e.source,
            target: e.target,
            weight: e.weight,
          })),
        });
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const handleNodeClick = useCallback(
    (node: EnrichedNode) => {
      navigate(`/sessions/${node.id}`);
    },
    [navigate],
  );

  if (loading) {
    return (
      <div className="space-y-6">
        <h2>Similarity Graph</h2>
        <Skeleton className="h-[500px] w-full rounded-lg" />
      </div>
    );
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="space-y-6">
        <h2>Similarity Graph</h2>
        <div className="border border-border rounded-lg p-12 text-center">
          <p className="text-muted-foreground">
            No graph data available. Run the seed script to generate embeddings
            and UMAP projections.
          </p>
          <code className="text-xs mt-2 block font-mono text-muted-foreground">
            python -m scripts.seed_embeddings
          </code>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2>Similarity Graph</h2>
          <p className="text-sm text-muted-foreground mt-1">
            {graphData.nodes.length} episodes, {graphData.links.length} connections
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs">
          {LEGEND_ITEMS.map((item) => (
            <div key={item.label} className="flex items-center gap-1.5">
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{ background: item.color }}
              />
              <span className="text-muted-foreground">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div
        ref={containerRef}
        className="border border-border rounded-lg bg-card overflow-hidden relative"
        style={{ height: "calc(100vh - 200px)" }}
      >
        <ForceGraph2D
          graphData={graphData}
          width={dimensions.width}
          height={dimensions.height}
          nodeRelSize={1}
          nodeVal={(node: EnrichedNode) => node.__size}
          nodeColor={(node: EnrichedNode) => node.__color}
          nodeLabel=""
          linkColor={() => "oklch(0.35 0 0)"}
          linkWidth={(link: EnrichedLink) => link.weight * 2}
          linkDirectionalParticles={0}
          backgroundColor="transparent"
          onNodeClick={handleNodeClick}
          onNodeHover={(node: EnrichedNode | null) => setHovered(node)}
          enableNodeDrag={true}
          enableZoomInteraction={true}
          cooldownTicks={100}
          nodeCanvasObject={(node: EnrichedNode, ctx: CanvasRenderingContext2D) => {
            const size = node.__size;
            ctx.beginPath();
            ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
            ctx.fillStyle = node.__color;
            ctx.fill();

            if (hovered && hovered.id === node.id) {
              ctx.strokeStyle = "oklch(0.98 0 0)";
              ctx.lineWidth = 1.5;
              ctx.stroke();
            }

            ctx.font = "3px 'IBM Plex Mono', monospace";
            ctx.fillStyle = "oklch(0.65 0 0)";
            ctx.textAlign = "center";
            ctx.fillText(node.label, node.x, node.y + size + 5);
          }}
        />

        {hovered && (
          <div className="absolute top-3 left-3 bg-popover border border-border rounded-md px-3 py-2 shadow-lg pointer-events-none z-10 max-w-xs">
            <p className="text-xs font-mono font-medium">{hovered.label}</p>
            {hovered.outcome && (
              <p className="text-xs text-muted-foreground mt-0.5">
                Outcome: {hovered.outcome}
              </p>
            )}
            {hovered.reward != null && (
              <p className="text-xs text-muted-foreground">
                Reward: {hovered.reward.toFixed(1)}
              </p>
            )}
            <p className="text-xs text-muted-foreground/50 mt-1">
              Click to view details
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
