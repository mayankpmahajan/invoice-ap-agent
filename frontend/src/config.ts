// The one place frontend tunables live (build-time env via Vite).
export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  dashboardRefreshMs: Number(import.meta.env.VITE_DASHBOARD_REFRESH_MS ?? 4000),
  runsPageSize: Number(import.meta.env.VITE_RUNS_PAGE_SIZE ?? 200),
  // While a run is live the page also polls, so a dropped event stream never freezes it.
  liveRunPollMs: Number(import.meta.env.VITE_LIVE_RUN_POLL_MS ?? 3000),
  // A read slower than this shows "taking longer than usual" (typical reads take 10-20 s).
  slowReadSeconds: Number(import.meta.env.VITE_SLOW_READ_SECONDS ?? 40),
} as const;
