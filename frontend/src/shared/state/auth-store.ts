import { create } from "zustand";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  userId: string | null;
  setSession: (values: { accessToken: string; refreshToken: string; userId: string }) => void;
  clearSession: () => void;
}

const ACCESS_TOKEN_STORAGE_KEY = "nanfo.auth.accessToken";
const REFRESH_TOKEN_STORAGE_KEY = "nanfo.auth.refreshToken";
const USER_ID_STORAGE_KEY = "nanfo.auth.userId";

function readStoredSession() {
  if (typeof window === "undefined") {
    return {
      accessToken: null,
      refreshToken: null,
      userId: null,
    };
  }

  return {
    accessToken: window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY),
    refreshToken: window.localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY),
    userId: window.localStorage.getItem(USER_ID_STORAGE_KEY),
  };
}

function persistSession(values: { accessToken: string | null; refreshToken: string | null; userId: string | null }) {
  if (typeof window === "undefined") {
    return;
  }

  if (values.accessToken) {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, values.accessToken);
  } else {
    window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  }

  if (values.refreshToken) {
    window.localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, values.refreshToken);
  } else {
    window.localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  }

  if (values.userId) {
    window.localStorage.setItem(USER_ID_STORAGE_KEY, values.userId);
  } else {
    window.localStorage.removeItem(USER_ID_STORAGE_KEY);
  }
}

const initialSession = readStoredSession();

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: initialSession.accessToken,
  refreshToken: initialSession.refreshToken,
  userId: initialSession.userId,
  setSession: ({ accessToken, refreshToken, userId }) =>
    set(() => {
      persistSession({ accessToken, refreshToken, userId });
      return {
        accessToken,
        refreshToken,
        userId,
      };
    }),
  clearSession: () =>
    set(() => {
      persistSession({
        accessToken: null,
        refreshToken: null,
        userId: null,
      });
      return {
        accessToken: null,
        refreshToken: null,
        userId: null,
      };
    }),
}));
