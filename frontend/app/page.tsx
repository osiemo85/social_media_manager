"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AuthForm } from "@/features/identity/components/auth-form";
import { api } from "@/lib/api-client";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => { api<{ user: { email: string } }>("/auth/me").then(() => router.replace("/dashboard")).catch(() => undefined); }, [router]);
  return <AuthForm onAuthenticated={() => router.replace("/dashboard")} />;
}
