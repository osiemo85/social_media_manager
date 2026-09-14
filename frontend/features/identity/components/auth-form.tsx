"use client";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api-client";

export function AuthForm({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [registering, setRegistering] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); try { setError(""); await api(`/auth/${registering ? "register" : "login"}`, { method: "POST", body: new FormData(event.currentTarget) }); onAuthenticated(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not authenticate."); } }
  return <main className="auth"><section className="auth-card"><p className="eyebrow">Consent-first social publishing</p><h1>{registering ? "Create your account" : "Welcome back"}</h1><p>Draft from work you control, then approve every post.</p>{error && <p className="notice error" role="alert">{error}</p>}<form onSubmit={submit}><label>Email<input name="email" type="email" required /></label><label>Password<input name="password" type="password" minLength={8} required /></label><button>{registering ? "Create account" : "Log in"}</button></form><button className="link" onClick={() => setRegistering(!registering)}>{registering ? "Already have an account? Log in" : "Need an account? Register"}</button></section></main>;
}
