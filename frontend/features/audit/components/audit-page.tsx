"use client";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api-client";
type Entry = { id: string | number; ts: string; provider: string; action: string; details: string };
const PAGE_SIZE = 10;

function formatTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function AuditPage() {
  const [entries, setEntries] = useState<Entry[]>([]); const [error, setError] = useState(""); const [page, setPage] = useState(1);
  useEffect(() => { api<{ ledger: Entry[] }>("/audit").then((result) => setEntries(result.ledger ?? [])).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load audit trail.")); }, []);
  const pageCount = Math.max(1, Math.ceil(entries.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const visibleEntries = useMemo(() => entries.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE), [entries, currentPage]);

  return <>
    <div className="page-heading"><div><p className="eyebrow">Governance</p><h1>Audit trail</h1></div><span className="count-pill">{entries.length} events</span></div>
    <p className="page-intro">A record of consent, source access, drafting, and publishing activity in this workspace.</p>
    {error && <p className="notice error" role="alert">{error}</p>}
    <article className="card compact-card audit-card">
      {entries.length ? <>
        <div className="table-wrap"><table className="compact-table"><thead><tr><th>When</th><th>Provider</th><th>Action</th><th>Details</th></tr></thead><tbody>{visibleEntries.map((entry) => <tr key={entry.id}><td className="nowrap">{formatTimestamp(entry.ts)}</td><td><span className="table-primary">{entry.provider}</span></td><td><span className="status-chip">{entry.action}</span></td><td className="details-cell" title={entry.details}>{entry.details}</td></tr>)}</tbody></table></div>
        <div className="pagination" aria-label="Audit pagination"><span className="pagination-summary">Showing {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, entries.length)} of {entries.length}</span><div className="pagination-controls"><button className="icon-button" aria-label="Previous page" title="Previous page" disabled={currentPage === 1} onClick={() => setPage((current) => current - 1)}>‹</button><span className="page-number">Page {currentPage} of {pageCount}</span><button className="icon-button" aria-label="Next page" title="Next page" disabled={currentPage === pageCount} onClick={() => setPage((current) => current + 1)}>›</button></div></div>
      </> : <p className="muted empty-state">No audit events yet.</p>}
    </article>
  </>;
}
