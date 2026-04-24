/**
 * Resolve the daemon connection info (port + token).
 *
 * When running inside Tauri, call the `daemon_info` IPC command; the
 * Rust host spawned the Python daemon and knows both values. When
 * running in plain vite dev or vitest, fall back to URL query
 * parameters so the standalone path still works for testing.
 */

export interface DaemonInfo {
  port: number;
  token: string;
}

interface TauriWindow extends Window {
  __TAURI_INTERNALS__?: unknown;
}

const isTauri = (): boolean =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in (window as TauriWindow);

export async function resolveDaemonInfo(): Promise<DaemonInfo | null> {
  if (isTauri()) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      return await invoke<DaemonInfo>("daemon_info");
    } catch (err) {
      console.error("failed to fetch daemon_info from Tauri:", err);
      return null;
    }
  }

  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const port = Number(params.get("port") ?? "0");
  const token = params.get("token") ?? "";
  if (!port || !token) return null;
  return { port, token };
}
