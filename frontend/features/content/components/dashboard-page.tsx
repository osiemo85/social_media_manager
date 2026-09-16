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
};
type PipelineOutcome = { draft_id: number; routed?: string };
type PipelineResult = { ingested: Record<string, number | string>; outcome: PipelineOutcome | null };

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
  const load = () => api<Dashboard>("/dashboard").then(setData).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load dashboard."));
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
      const result = await api<PipelineResult>("/pipeline/run", { method: "POST" });
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
    <article className="card"><h2>Pipeline</h2><p>Ingest connected sources, create a grounded draft, and route it through the publishing rules.</p><button className="secondary" onClick={runPipeline} disabled={pipelineRunning} aria-describedby="pipeline-status">{pipelineRunning && <span className="spinner" aria-hidden="true" />} {pipelineRunning ? "Running pipeline…" : "Run pipeline now"}</button><p id="pipeline-status" className="pipeline-status" role="status" aria-live="polite">{pipelineRunning ? "Pipeline is running. Fetching authorized sources and preparing any available draft." : ""}</p></article>
  </>;
}
