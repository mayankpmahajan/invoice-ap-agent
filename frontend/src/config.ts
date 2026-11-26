// The one place frontend tunables live (build-time env via Vite).
export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  dashboardRefreshMs: Number(import.meta.env.VITE_DASHBOARD_REFRESH_MS ?? 4000),
  runsPageSize: Number(import.meta.env.VITE_RUNS_PAGE_SIZE ?? 200),
} as const;
