"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
type Data = { mode?: string; runs_per_day?: number; schedule_choices?: number[] };
export function SettingsPage() {
  const [data, setData] = useState<Data>({}); const [mode, setMode] = useState("review"); const [runs, setRuns] = useState(0); const [notice, setNotice] = useState(""); const [error, setError] = useState("");
  useEffect(() => { api<Data>("/settings").then((result) => { setData(result); setMode(result.mode ?? "review"); setRuns(result.runs_per_day ?? 0); }).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load settings.")); }, []);
  const choices = data.schedule_choices ?? [0, 1, 2, 3, 4, 6, 12, 24];
  return <><h1>Settings</h1>{notice && <p className="notice success" role="status">{notice}</p>}{error && <p className="notice error" role="alert">{error}</p>}<article className="card"><label>Publishing mode<select value={mode} onChange={(event) => setMode(event.target.value)}><option value="review">Review — approve every post</option><option value="auto">Auto-publish — requires explicit consent</option></select></label><label>Scheduled runs per day<select value={runs} onChange={(event) => setRuns(Number(event.target.value))}>{choices.map((value) => <option value={value} key={value}>{value === 0 ? "Off — manual only" : `${value}× per day`}</option>)}</select></label><button onClick={async () => { try { await api("/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, runs_per_day: runs }) }); setError(""); setNotice("Settings saved."); } catch (cause) { setNotice(""); setError(cause instanceof Error ? cause.message : "Could not save settings."); } }}>Save settings</button></article></>;
}
