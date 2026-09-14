"use client";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api-client";
type Dashboard = Record<string, string | number | undefined>;
export function DashboardPage() {
  const [data, setData] = useState<Dashboard>({}); const [notice, setNotice] = useState(""); const [error, setError] = useState("");
  const load = () => api<Dashboard>("/dashboard").then(setData).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load dashboard."));
  useEffect(() => { load(); }, []);
  const done = (message: string) => { setError(""); setNotice(message); load(); };
  async function create(event: FormEvent<HTMLFormElement>) { event.preventDefault(); try { const result = await api<{ draft_id: string }>("/drafts", { method: "POST", body: new FormData(event.currentTarget) }); event.currentTarget.reset(); done(`Draft #${result.draft_id} created and sent to review.`); } catch (cause) { done(cause instanceof Error ? cause.message : "Could not create a draft."); } }
  const stats = [[data.pending, "Pending review"], [data.published, "Published"], [data.unused, "Unused signals"], [data.mode, "Publishing mode"], [`${data.schedule ?? 0}/day`, "Scheduled runs"]];
  return <><h1>Dashboard</h1>{notice && <p className="notice success" role="status">{notice}</p>}{error && <p className="notice error" role="alert">{error}</p>}<div className="stats">{stats.map(([value, name]) => <article className="card stat" key={name}><strong>{String(value ?? "—")}</strong><span>{name}</span></article>)}</div><article className="card"><h2>Manual draft</h2><p>Direct input needs no account connection.</p><form onSubmit={create}><label>What did you work on?<input name="hint" placeholder="Shipped retry logic for the connector layer today" /></label><label>Or add a supported file<input name="file" type="file" accept=".md,.txt,.py,.ipynb,.json,.rst,.csv" /></label><button>Create draft</button></form></article><article className="card"><h2>Pipeline</h2><p>Ingest connected sources, create a grounded draft, and route it through the publishing rules.</p><button className="secondary" onClick={async () => { try { await api("/pipeline/run", { method: "POST" }); done("Pipeline completed."); } catch (cause) { done(cause instanceof Error ? cause.message : "Pipeline failed."); } }}>Run pipeline now</button></article></>;
}
