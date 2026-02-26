import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type SearchResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { outcomeVariant, sessionDisplayName } from "@/lib/utils";
import { Search } from "lucide-react";

export function SearchView() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setSearched(true);
    try {
      const res = await api.search(query.trim());
      setResults(res);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2>Search Sessions</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Natural language search over session summaries
        </p>
      </div>

      <div className="flex gap-2">
        <Input
          type="search"
          placeholder="e.g. successful episodes with high reward..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          className="flex-1"
        />
        <Button onClick={handleSearch} disabled={loading || !query.trim()}>
          <Search className="w-4 h-4 mr-1.5" />
          Search
        </Button>
      </div>

      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      )}

      {!loading && searched && results.length === 0 && (
        <div className="border border-border rounded-lg p-12 text-center">
          <p className="text-muted-foreground">
            No results found. Make sure embeddings have been generated.
          </p>
          <code className="text-xs mt-2 block font-mono text-muted-foreground">
            python -m scripts.seed_embeddings
          </code>
        </div>
      )}

      {!loading && results.length > 0 && (
        <div className="space-y-2">
          {results.map((r, i) => (
            <div
              key={r.session.session_id}
              className="flex items-center gap-4 border border-border rounded-lg p-4 hover:bg-muted/30 cursor-pointer transition-colors"
              onClick={() => navigate(`/sessions/${r.session.session_id}`)}
            >
              <span className="text-xs font-mono text-muted-foreground w-6">
                #{i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm">
                    {sessionDisplayName(r.session.session_id, r.session.episode_index, 12)}
                  </span>
                  <Badge
                    variant={
                      r.session.source === "live" ? "secondary" : "outline"
                    }
                  >
                    {r.session.source}
                  </Badge>
                  {r.session.outcome && (
                    <Badge variant={outcomeVariant(r.session.outcome)}>
                      {r.session.outcome}
                    </Badge>
                  )}
                </div>
                {r.session.summary && (
                  <p className="text-xs text-muted-foreground mt-1 truncate">
                    {r.session.summary}
                  </p>
                )}
              </div>
              <div className="text-right">
                <p className="text-sm font-mono">
                  {(r.score * 100).toFixed(1)}%
                </p>
                <p className="text-xs text-muted-foreground">match</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
