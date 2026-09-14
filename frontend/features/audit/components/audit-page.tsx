"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
type Entry = { id: string | number; ts: string; provider: string; action: string; details: string };
export function AuditPage() {
  const [entries, setEntries] = useState<Entry[]>([]); const [error, setError] = useState("");
  useEffect(() => { api<{ ledger: Entry[] }>("/audit").then((result) => setEntries(result.ledger ?? [])).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load audit trail.")); }, []);
  return <><h1>Audit trail</h1>{error && <p className="notice error" role="alert">{error}</p>}<article className="card">{entries.length ? <table><thead><tr><th>When</th><th>Provider</th><th>Action</th><th>Details</th></tr></thead><tbody>{entries.map((entry) => <tr key={entry.id}><td>{entry.ts}</td><td>{entry.provider}</td><td>{entry.action}</td><td>{entry.details}</td></tr>)}</tbody></table> : <p className="muted">No audit events yet.</p>}</article></>;
}
