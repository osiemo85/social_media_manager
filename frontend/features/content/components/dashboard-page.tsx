"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api-client";

type PublishedPost = { id: string | number; text: string; published_at: string | null };
type Dashboard = {
  pending?: number;
  published?: number;
  unused?: number;
  mode?: string;
  schedule?: number;
  recent?: PublishedPost[];
  connections?: Connection[];
};
type Policy = { max_items?: number; lookback_hours?: number; folder_id?: string };
type Connection = { provider: string; status: string; meta?: { policy?: Policy } };
type PipelineOutcome = { draft_id: number; routed?: string };
type PipelineResult = { ingested: Record<string, number | string>; outcome: PipelineOutcome | null };

function sourceState(connections: Connection[] = []) {
  const enabled: Record<string, boolean> = {};
  const limits: Record<string, { max_items: number; lookback_hours: number }> = {};
  for (const connection of connections) {
    if (connection.status !== "active" || !["github", "filesystem", "gmail", "google_drive"].includes(connection.provider)) continue;
    if (connection.provider === "google_drive" && !connection.meta?.policy?.folder_id) continue;
    enabled[connection.provider] = true;
    if (["gmail", "google_drive"].includes(connection.provider)) limits[connection.provider] = { max_items: connection.meta?.policy?.max_items ?? (connection.provider === "gmail" ? 5 : 4), lookback_hours: connection.meta?.policy?.lookback_hours ?? 24 };
  }
  return { enabled, limits };
}

function pipelineMessage(result: PipelineResult): string {
  const sources = Object.entries(result.ingested).map(([source, value]) => `${source}: ${typeof value === "number" ? `${value} signal${value === 1 ? "" : "s"}` : value}`).join("; ");
  if (!result.outcome) return `Pipeline completed. ${sources || "No new signals found."}`;
  return `Pipeline completed.${sources ? ` ${sources}.` : ""} Draft #${result.outcome.draft_id}${result.outcome.routed ? ` routed to ${result.outcome.routed}` : " created"}.`;
}

export function DashboardPage() {
  const [data, setData] = useState<Dashboard>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [expandedPosts, setExpandedPosts] = useState<Set<string | number>>(new Set());
  const [sourceEnabled, setSourceEnabled] = useState<Record<string, boolean>>({});
  const [sourceLimits, setSourceLimits] = useState<Record<string, { max_items: number; lookback_hours: number }>>({});
  const load = () => api<Dashboard>("/dashboard").then((result) => { const state = sourceState(result.connections); setData(result); setSourceEnabled(state.enabled); setSourceLimits(state.limits); }).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load dashboard."));
  useEffect(() => { load(); }, []);
  const done = (message: string) => { setError(""); setNotice(message); load(); };

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const result = await api<{ draft_id: string }>("/drafts", { method: "POST", body: new FormData(event.currentTarget) });
      event.currentTarget.reset();
      done(`Draft #${result.draft_id} created and sent to review.`);
    } catch (cause) {
      done(cause instanceof Error ? cause.message : "Could not create a draft.");
    }
  }

  async function runPipeline() {
    setPipelineRunning(true);
    setError("");
    setNotice("");
    try {
      const sources = Object.fromEntries(Object.entries(sourceEnabled).map(([name, enabled]) => [name, { enabled, ...(sourceLimits[name] ?? {}) }]));
      const result = await api<PipelineResult>("/pipeline/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sources }) });
      done(pipelineMessage(result));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Pipeline failed.");
    } finally {
      setPipelineRunning(false);
    }
  }

  const stats = [[data.pending, "Pending review"], [data.published, "Published"], [data.unused, "Unused signals"], [data.mode, "Publishing mode"], [`${data.schedule ?? 0}/day`, "Scheduled runs"]];
  const recentPosts = data.recent ?? [];
  return <>
    <h1>Dashboard</h1>
    {notice && <p className="notice success" role="status">{notice}</p>}
    {error && <p className="notice error" role="alert">{error}</p>}
    <div className="stats">{stats.map(([value, name]) => <article className="card stat" key={name}><strong>{String(value ?? "—")}</strong><span>{name}</span></article>)}</div>
    <article className="card"><h2>Previous published posts</h2><p>These are the recent posts the drafting agent uses as reference to avoid repetition.</p>{recentPosts.length ? <ol className="published-posts">{recentPosts.map((post) => { const expanded = expandedPosts.has(post.id); return <li key={post.id}><p className={expanded ? "" : "post-preview"}>{post.text}</p><button className="link post-toggle" type="button" aria-expanded={expanded} onClick={() => setExpandedPosts((current) => { const next = new Set(current); if (next.has(post.id)) next.delete(post.id); else next.add(post.id); return next; })}>{expanded ? "Show less" : "Show more"}</button><span className="muted">Published {post.published_at ? new Date(post.published_at).toLocaleString() : "date unavailable"}</span></li>; })}</ol> : <p className="muted">No posts have been published yet.</p>}</article>
    <article className="card"><h2>Manual draft</h2><p>Direct input needs no account connection.</p><form onSubmit={create}><label>What did you work on?<input name="hint" placeholder="Shipped retry logic for the connector layer today" /></label><label>Or add a supported file<input name="file" type="file" accept=".md,.txt,.py,.ipynb,.json,.rst,.csv" /></label><button>Create draft</button></form></article>
    <article className="card"><h2>Pipeline</h2><p>Choose connected sources, ingest only bounded recent items, create one grounded draft, and route it through review.</p>{Object.keys(sourceEnabled).length ? <fieldset><legend>Sources for this run</legend>{Object.keys(sourceEnabled).map((source) => <div className="run-source" key={source}><label className="check"><input type="checkbox" checked={sourceEnabled[source]} onChange={(event) => setSourceEnabled({ ...sourceEnabled, [source]: event.target.checked })} />{source.replace("_", " ")}</label>{sourceLimits[source] && sourceEnabled[source] && <div className="source-policy"><label>Maximum<input type="number" min={1} max={20} value={sourceLimits[source].max_items} onChange={(event) => setSourceLimits({ ...sourceLimits, [source]: { ...sourceLimits[source], max_items: Number(event.target.value) } })} /></label><label>Lookback<select value={sourceLimits[source].lookback_hours} onChange={(event) => setSourceLimits({ ...sourceLimits, [source]: { ...sourceLimits[source], lookback_hours: Number(event.target.value) } })}><option value={24}>24 hours</option><option value={48}>48 hours</option><option value={168}>7 days</option></select></label></div>}</div>)}</fieldset> : <p className="muted">Connect a source to run the ingestion pipeline.</p>}<button className="secondary" onClick={runPipeline} disabled={pipelineRunning || !Object.values(sourceEnabled).some(Boolean)} aria-describedby="pipeline-status">{pipelineRunning && <span className="spinner" aria-hidden="true" />} {pipelineRunning ? "Running pipeline…" : "Run pipeline now"}</button><p id="pipeline-status" className="pipeline-status" role="status" aria-live="polite">{pipelineRunning ? "Pipeline is running. Fetching authorized sources and preparing any available draft." : ""}</p></article>
  </>;
}
