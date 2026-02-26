import type { ReactNode } from "react";
import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
import { SessionDetail } from "@/components/SessionDetail";
import { SessionList } from "@/components/SessionList";
import { SimilarityGraph } from "@/components/SimilarityGraph";
import { SearchView } from "@/components/SearchBar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { List, Network, Search } from "lucide-react";

const NAV_ITEMS = [
  { to: "/sessions", icon: List, label: "Sessions" },
  { to: "/graph", icon: Network, label: "Graph" },
  { to: "/search", icon: Search, label: "Search" },
] as const;

function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <nav className="w-52 shrink-0 border-r border-sidebar-border bg-sidebar flex flex-col">
        <div className="px-4 py-5 border-b border-sidebar-border">
          <h1 className="text-sm font-semibold tracking-wide text-sidebar-foreground">
            Robot Sessions
          </h1>
          <p className="text-[10px] text-muted-foreground mt-0.5 font-mono">
            Telemetry Dashboard
          </p>
        </div>

        <div className="flex-1 py-3 px-2 space-y-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                    : "text-muted-foreground hover:text-sidebar-foreground hover:bg-sidebar-accent/50"
                )
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <main className="flex-1 overflow-auto p-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <TooltipProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/sessions" replace />} />
            <Route path="/sessions" element={<SessionList />} />
            <Route path="/sessions/:id" element={<SessionDetail />} />
            <Route path="/graph" element={<SimilarityGraph />} />
            <Route path="/search" element={<SearchView />} />
          </Routes>
        </Layout>
      </TooltipProvider>
    </BrowserRouter>
  );
}
