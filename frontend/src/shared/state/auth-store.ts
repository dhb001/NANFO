import { create } from "zustand";
import type { UserProfile } from "@/shared/types/auth";
import { tabIdentity, type TabOwnership } from "@/shared/state/tab-identity";

interface Session {
  accessToken: string;
  refreshToken: string;
  userId: string;
}

/** Transient refresh failure (502/503/network/timeout): the session is kept and retried (ADR-028). */
export interface SessionRecovery {
  retryAt: number;
  attempt: number;
  reason: "refresh_unavailable" | "profile_unavailable";
}

export type SessionNotice = "copied_tab" | null;

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  userId: string | null;
  profile: UserProfile | null;
  generation: number;
  endingSession: boolean;
  /** null while this tab's duplicate check is pending (see tab-identity.ts). */
  ownership: TabOwnership | null;
  recovery: SessionRecovery | null;
  notice: SessionNotice;
  setSession: (values: Session & { profile: UserProfile }) => void;
  replaceTokens: (values: Pick<Session, "accessToken" | "refreshToken"> & { profile?: UserProfile }) => void;
  setProfile: (profile: UserProfile) => void;
  setRecovery: (recovery: SessionRecovery | null) => void;
  clearSession: () => void;
}

const SESSION_KEY = "nanfo.auth.session";

function discardSharedSession() {
  try {
    for (const key of ["session", "accessToken", "refreshToken", "userId"]) {
      window.localStorage.removeItem(`nanfo.auth.${key}`);
    }
  } catch {
    // Shared storage may be unavailable; never read credentials from it.
  }
}

function readSession(): Session | null {
  discardSharedSession();
  try {
    // An opener can copy sessionStorage to a new tab. Never inherit that token family.
    const navigation = performance.getEntriesByType?.("navigation")[0];
    if (window.opener && !(navigation && "type" in navigation && navigation.type === "reload")) {
      window.sessionStorage.removeItem(SESSION_KEY);
      return null;
    }
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    const value: unknown = raw ? JSON.parse(raw) : null;
    if (value && typeof value === "object" &&
        "accessToken" in value && typeof value.accessToken === "string" &&
        "refreshToken" in value && typeof value.refreshToken === "string" &&
        "userId" in value && typeof value.userId === "string") {
      return { accessToken: value.accessToken, refreshToken: value.refreshToken, userId: value.userId };
    }
  } catch {
    // Unavailable or invalid storage requires a fresh login.
  }
  return null;
}

function persistSession(session: Session | null) {
  discardSharedSession();
  try {
    // Rotation single-flight and persistence have the same tab-local lifetime.
    if (session) window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // The in-memory session remains usable when storage is unavailable.
  }
}

const initialSession = readSession();

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: initialSession?.accessToken ?? null,
  refreshToken: initialSession?.refreshToken ?? null,
  userId: initialSession?.userId ?? null,
  profile: null,
  generation: 0,
  endingSession: false,
  ownership: tabIdentity.state(),
  recovery: null,
  notice: null,
  setSession: ({ profile, ...session }) => set((state) => {
    persistSession(session);
    return { ...session, profile, generation: state.generation + 1, endingSession: false, recovery: null, notice: null };
  }),
  replaceTokens: (tokens) => set((state) => {
    if (!state.userId) return state;
    persistSession({ accessToken: tokens.accessToken, refreshToken: tokens.refreshToken, userId: state.userId });
    return tokens;
  }),
  setProfile: (profile) => set({ profile }),
  setRecovery: (recovery) => set({ recovery }),
  clearSession: () => set((state) => {
    persistSession(null);
    return { accessToken: null, refreshToken: null, userId: null, profile: null,
      generation: state.generation + 1, endingSession: false, recovery: null };
  }),
}));

// A copied tab drops the inherited credentials locally. It never calls logout:
// revoking would sign out the original tab that legitimately owns the family.
void tabIdentity.ownership.then((ownership) => {
  const state = useAuthStore.getState();
  if (ownership === "duplicate" && initialSession && state.generation === 0 && state.accessToken === initialSession.accessToken) {
    state.clearSession();
    useAuthStore.setState({ ownership, notice: "copied_tab" });
  } else {
    useAuthStore.setState({ ownership });
  }
});
