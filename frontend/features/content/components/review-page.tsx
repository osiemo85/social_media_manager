"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
type Draft = { id: string | number; text: string; created_at: string };
export function ReviewPage() {
  const [drafts, setDrafts] = useState<Draft[]>([]); const [notice, setNotice] = useState(""); const [error, setError] = useState("");
  const load = () => api<{ drafts: Draft[] }>("/drafts").then((result) => setDrafts(result.drafts ?? [])).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load drafts."));
  useEffect(() => { load(); }, []);
  const done = (message: string) => { setError(""); setNotice(message); load(); };
  return <><h1>Review queue</h1><p>Nothing is published without your approval unless you separately opt into auto-publishing.</p>{notice && <p className="notice success" role="status">{notice}</p>}{error && <p className="notice error" role="alert">{error}</p>}{drafts.length === 0 ? <article className="card">No pending drafts.</article> : drafts.map((draft) => <DraftCard key={draft.id} draft={draft} done={done} />)}</>;
}
function DraftCard({ draft, done }: { draft: Draft; done: (message: string) => void }) {
  const [text, setText] = useState(draft.text); async function action(path: string, init: RequestInit) { try { await api(path, init); done(`Draft #${draft.id} updated.`); } catch (cause) { done(cause instanceof Error ? cause.message : "Action failed."); } }
  return <article className="card"><h2>Draft #{draft.id}</h2><p className="muted">Created {draft.created_at}</p><textarea value={text} onChange={(event) => setText(event.target.value)} /><div className="actions"><button onClick={() => action(`/drafts/${draft.id}/publish`, { method: "POST" })}>Publish</button><button className="secondary" onClick={() => action(`/drafts/${draft.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })}>Save edit</button><button className="danger" onClick={() => action(`/drafts/${draft.id}/reject`, { method: "POST" })}>Reject</button></div></article>;
}
