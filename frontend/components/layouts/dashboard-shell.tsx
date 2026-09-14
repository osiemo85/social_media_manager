"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

const navigation = [["Dashboard", "/dashboard"], ["Review", "/review"], ["Connections", "/connections"], ["Settings", "/settings"], ["Audit", "/audit"]] as const;
export function DashboardShell({ children }: { children: React.ReactNode }) {
  const [email, setEmail] = useState<string>(); const pathname = usePathname(); const router = useRouter();
  useEffect(() => { api<{ user: { email: string } }>("/auth/me").then((result) => setEmail(result.user.email)).catch(() => router.replace("/")); }, [router]);
  if (!email) return <main className="shell"><p className="muted">Loading your workspace…</p></main>;
  return <main className="workspace"><aside className="sidebar"><Link className="brand" href="/dashboard">Social Media Manager</Link><nav aria-label="Workspace">{navigation.map(([name, href]) => <Link key={href} className={pathname === href ? "nav active" : "nav"} href={href}>{name}</Link>)}</nav><div className="account"><span>{email}</span><button className="link" onClick={async () => { await api("/auth/logout", { method: "POST" }); router.replace("/"); }}>Log out</button></div></aside><section className="shell">{children}</section></main>;
}
