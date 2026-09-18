"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api-client";

type SourcePolicy = { max_items: number; lookback_hours: number; scheduled_enabled: boolean; label_ids?: string[]; folder_id?: string; folder_name?: string };
type Connection = { provider: string; scopes: string[]; expires_at: string; status: string; meta: { account?: string; policy?: SourcePolicy; retention?: string; revocation_url?: string } };
type Data = { connections: Connection[]; platforms: string[]; source_defaults: Record<string, SourcePolicy>; lookback_choices: number[]; source_max_items: number };
type Label = { id: string; name: string };
type Folder = { id: string; name: string };

export function ConnectionsPage() {
  const [data, setData] = useState<Data>({ connections: [], platforms: [], source_defaults: {}, lookback_choices: [24, 48, 168], source_max_items: 20 });
  const [selected, setSelected] = useState(["linkedin"]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = () => api<Data>("/connections").then(setData).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load connections.")).finally(() => setLoading(false));
  useEffect(() => { void load(); }, []);
  const succeed = (message: string) => { setError(""); setNotice(message); void load(); };
  const fail = useCallback((cause: unknown) => { setNotice(""); setError(cause instanceof Error ? cause.message : "Connection failed."); }, []);
  const connection = (provider: string) => data.connections.find((item) => item.provider === provider);

  async function connectPublisher(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); selected.forEach((platform) => form.append("platforms", platform));
    try { await api("/connections/upload-post", { method: "POST", body: form }); succeed("Publishing consent was saved."); } catch (cause) { fail(cause); }
  }
  async function startOAuth(provider: "github" | "gmail" | "google-drive") {
    try { const result = await api<{ authorization_url: string }>(`/connections/${provider}/start`); window.location.assign(result.authorization_url); } catch (cause) { fail(cause); }
  }
  async function disconnect(provider: string) {
    const retained = provider === "gmail" || provider === "google_drive" ? " Generated drafts remain until you delete them." : "";
    if (!window.confirm(`Disconnect ${provider} and purge its cached source data?${retained}`)) return;
    try { await api(`/connections/${provider}`, { method: "DELETE" }); succeed(`${provider} disconnected and cached source data purged.`); } catch (cause) { fail(cause); }
  }

  return <>
    <div className="page-heading"><div><p className="eyebrow">Workspace access</p><h1>Connections &amp; consent</h1></div><span className="count-pill">90-day default</span></div>
    <p className="page-intro">Each source is optional and separately controlled. Revoke access any time; cached source data is removed when you disconnect.</p>
    {notice && <p className="notice success" role="status">{notice}</p>}
    {error && <p className="notice error" role="alert">{error}</p>}
    <article className="card compact-card"><div className="section-heading"><div><h2>Current connections</h2><p className="muted">Active permissions and their expiry.</p></div></div>{loading ? <p className="muted empty-state">Loading connections…</p> : data.connections.length ? <div className="table-wrap"><table className="compact-table connections-table"><thead><tr><th>Provider</th><th>Account</th><th>Access</th><th>Expiry</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{data.connections.map((item) => <tr key={item.provider}><td><span className="provider-name">{item.provider}</span></td><td>{item.meta.account ?? <span className="muted">Not provided</span>}</td><td><span className="status-chip success-chip">{item.status}</span></td><td className="nowrap">{new Date(item.expires_at).toLocaleDateString([], { dateStyle: "medium" })}</td><td className="action-cell"><button className="icon-button danger-icon" aria-label={`Disconnect ${item.provider} and purge cached data`} title={`Disconnect ${item.provider} and purge cached data`} onClick={() => disconnect(item.provider)}><span aria-hidden="true">↪</span><span className="icon-button-label">Disconnect &amp; purge</span></button></td></tr>)}</tbody></table></div> : <p className="muted empty-state">Nothing connected — manual mode is still fully available.</p>}</article>

    <div className="connection-grid">
      <GoogleSourceCard key={`gmail-${connection("gmail")?.expires_at ?? "new"}`} provider="gmail" title="Gmail" description="Read bounded recent messages from labels you choose. Attachments are never fetched." connection={connection("gmail")} defaults={data.source_defaults.gmail} lookbacks={data.lookback_choices} maxItems={data.source_max_items} onConnect={() => startOAuth("gmail")} onSaved={succeed} onError={fail} />
      <GoogleSourceCard key={`drive-${connection("google_drive")?.expires_at ?? "new"}`} provider="google_drive" title="Google Drive" description="Read recent Google Docs, text, Markdown, and PDF files inside one folder you choose." connection={connection("google_drive")} defaults={data.source_defaults.google_drive} lookbacks={data.lookback_choices} maxItems={data.source_max_items} onConnect={() => startOAuth("google-drive")} onSaved={succeed} onError={fail} />
      <article className="card connection-card"><div className="card-title-row"><div><p className="provider-kicker">Source</p><h2>GitHub <span className="read-only">Read-only</span></h2></div><span className={`status-dot ${connection("github")?.status === "active" ? "active" : ""}`}>{connection("github")?.status === "active" ? "Connected" : "Optional"}</span></div><p>Fetch recent repository activity. GitHub consent is independent of Google.</p><div className="card-footer"><button className="secondary" onClick={() => startOAuth("github")}>{connection("github")?.status === "active" ? "Reconnect" : "Connect GitHub"}</button><details><summary>More</summary><p className="muted">Only the minimum activity needed for drafting is read. Access expires with your consent.</p></details></div></article>
    </div>

    <article className="card"><h2>Publishing via Upload-Post</h2><p>Choose exactly which platforms this app may publish to.</p><form onSubmit={connectPublisher}><label>Upload-Post API key<input name="api_key" type="password" required /></label><label>Upload-Post username<input name="username" required /></label><fieldset><legend>Allowed platforms</legend>{data.platforms.map((platform) => <label className="check" key={platform}><input type="checkbox" checked={selected.includes(platform)} onChange={() => setSelected(selected.includes(platform) ? selected.filter((item) => item !== platform) : [...selected, platform])} />{platform}</label>)}</fieldset><label className="check"><input name="auto_publish" type="checkbox" />Allow auto-publish as separate consent</label><button>Grant publishing consent</button></form></article>
  </>;
}

function GoogleSourceCard({ provider, title, description, connection, defaults, lookbacks, maxItems, onConnect, onSaved, onError }: { provider: "gmail" | "google_drive"; title: string; description: string; connection?: Connection; defaults?: SourcePolicy; lookbacks: number[]; maxItems: number; onConnect: () => void; onSaved: (message: string) => void; onError: (cause: unknown) => void }) {
  const initial = connection?.meta.policy ?? defaults;
  const [max, setMax] = useState(initial?.max_items ?? (provider === "gmail" ? 5 : 4));
  const [lookback, setLookback] = useState(initial?.lookback_hours ?? 24);
  const [scheduled, setScheduled] = useState(initial?.scheduled_enabled ?? false);
  const [labels, setLabels] = useState<Label[]>([]);
  const [selectedLabels, setSelectedLabels] = useState<string[]>(initial?.label_ids ?? ["INBOX"]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [folderQuery, setFolderQuery] = useState("");
  const [folderId, setFolderId] = useState(initial?.folder_id ?? "");
  const active = connection?.status === "active";

  useEffect(() => {
    if (!active) return;
    if (provider === "gmail") api<{ labels: Label[] }>("/connections/gmail/labels").then((result) => setLabels(result.labels)).catch(onError);
    else api<{ folders: Folder[] }>("/connections/google-drive/folders").then((result) => setFolders(result.folders)).catch(onError);
  }, [active, provider, onError]);

  async function save() {
    const folder = folders.find((item) => item.id === folderId);
    const body = { max_items: max, lookback_hours: lookback, scheduled_enabled: scheduled, ...(provider === "gmail" ? { label_ids: selectedLabels } : { folder_id: folderId, folder_name: folder?.name ?? initial?.folder_name ?? "" }) };
    try { await api(`/connections/${provider}/settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); onSaved(`${title} fetch settings saved.`); } catch (cause) { onError(cause); }
  }

  async function searchFolders() {
    try {
      const result = await api<{ folders: Folder[] }>(`/connections/google-drive/folders?q=${encodeURIComponent(folderQuery)}`);
      setFolders(result.folders);
    } catch (cause) { onError(cause); }
  }

  return <article className="card connection-card"><div className="card-title-row"><div><p className="provider-kicker">Source</p><h2>{title} <span className="read-only">Read-only</span></h2></div><span className={`status-dot ${active ? "active" : ""}`}>{active ? "Connected" : "Optional"}</span></div><p>{description}</p>{!active ? <div className="card-footer"><button className="secondary" onClick={onConnect}>Connect {title}</button><details><summary>More</summary><p className="muted">Extracted source text is cleared after drafting. Scheduled access is off until you enable it.</p></details></div> : <><p className="connection-status">Connected as {connection?.meta.account ?? "Google account"}</p><details className="settings-details"><summary>Source settings</summary><div className="source-policy"><label>Maximum items per run<input type="number" min={1} max={maxItems} value={max} onChange={(event) => setMax(Number(event.target.value))} /></label><label>Lookback<select value={lookback} onChange={(event) => setLookback(Number(event.target.value))}>{lookbacks.map((hours) => <option key={hours} value={hours}>{hours === 168 ? "7 days" : `${hours} hours`}</option>)}</select></label></div>{provider === "gmail" ? <fieldset><legend>Allowed labels</legend>{labels.map((label) => <label className="check" key={label.id}><input type="checkbox" checked={selectedLabels.includes(label.id)} onChange={() => setSelectedLabels(selectedLabels.includes(label.id) ? selectedLabels.filter((id) => id !== label.id) : [...selectedLabels, label.id])} />{label.name}</label>)}</fieldset> : <><label>Find a Drive folder<input value={folderQuery} onChange={(event) => setFolderQuery(event.target.value)} placeholder="Folder name" /></label><button type="button" className="secondary small" onClick={searchFolders}>Search folders</button><label>Allowed folder<select value={folderId} onChange={(event) => setFolderId(event.target.value)}><option value="">Choose a folder</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label></>}<label className="check"><input type="checkbox" checked={scheduled} onChange={(event) => setScheduled(event.target.checked)} />Allow this source in scheduled runs</label><div className="actions"><button onClick={save}>Save source settings</button><button className="secondary" onClick={onConnect}>Reconnect</button></div></details></>}</article>;
}
