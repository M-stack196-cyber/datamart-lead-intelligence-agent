import type { SupabaseClient, Session } from "@supabase/supabase-js";

export const SESSION_EXPIRED_MESSAGE = "Session expired. Please sign in again.";

export function apiBase() {
  return process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "production" ? "/api" : "http://localhost:8000");
}

export async function getFreshAccessToken(supabase: SupabaseClient) {
  const { data } = await supabase.auth.getSession();
  let session: Session | null = data.session;

  if (!session) return null;

  const expiresAtMs = session.expires_at ? session.expires_at * 1000 : 0;
  const shouldRefresh = Boolean(expiresAtMs && expiresAtMs - Date.now() < 60_000);

  if (shouldRefresh) {
    const refreshed = await supabase.auth.refreshSession();
    session = refreshed.data.session;
  }

  return session?.access_token ?? null;
}

export async function expireFrontendSession(supabase: SupabaseClient) {
  await supabase.auth.signOut().catch(() => undefined);
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem("datamart_auth_message", SESSION_EXPIRED_MESSAGE);
    window.location.replace("/login");
  }
}

export async function authenticatedFetch(
  supabase: SupabaseClient,
  path: string,
  init: RequestInit = {},
) {
  const token = await getFreshAccessToken(supabase);
  if (!token) {
    await expireFrontendSession(supabase);
    throw new Error(SESSION_EXPIRED_MESSAGE);
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(apiBase() + path, { ...init, headers });
  if (response.status === 401) {
    await expireFrontendSession(supabase);
    throw new Error(SESSION_EXPIRED_MESSAGE);
  }

  return response;
}
