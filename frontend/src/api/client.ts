import createClient from "openapi-fetch";
import type { components, paths } from "./schema"; // generated from the backend OpenAPI: npm run gen:api
import { config } from "../config";

export const api = createClient<paths>({ baseUrl: config.apiBaseUrl });

export type RunSummary = components["schemas"]["RunSummary"];
export type RunDetail = components["schemas"]["RunDetail"];
export type RunEvent = components["schemas"]["EventOut"];
export type Stats = components["schemas"]["Stats"];

/** Unwraps an openapi-fetch result: throws on error so react-query's error state handles it. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || data === undefined) {
    const detail = (error as { detail?: string } | undefined)?.detail;
    throw new Error(detail ?? `Request failed (${response.status})`);
  }
  return data;
}

// Shapes of the pipeline's result payload (stored as JSON on the run).
export type Outcome = "pass" | "info" | "review" | "reject";
export interface Check { id: string; title: string; outcome: Outcome; detail: string; evidence: Record<string, unknown> }
export interface Field<T = string> { value: T | null; confidence: "sure" | "leaning" | "torn"; page: number | null; quote: string | null }
export interface LineItem { description: string; sku: string | null; quantity: number | null; unit_price: number | null; amount: number | null; page: number; quote: string; confidence: Field["confidence"] }
export interface Extraction {
  document_type: string; vendor_name: Field; vendor_tax_id: Field; vendor_bank_account: Field; invoice_number: Field;
  invoice_date: Field; due_date: Field; currency: Field; po_reference: Field; line_items: LineItem[];
  subtotal: Field<number>; tax_amount: Field<number>; total: Field<number>; amounts_include_tax: boolean; doubts: string;
}
export interface LlmCall { role: string; model: string; prompt_ref: string; params: Record<string, unknown>; latency_ms: number; input_tokens: number | null; output_tokens: number | null; attempts: number }
export interface RunResult {
  headline?: string;
  decision: string; summary: string; checks: Check[]; extraction: Extraction; page_count: number;
  match: { how: string; llm?: boolean; settled_by?: string; confidence?: string; doubt?: string; po_number?: string | null; line_map?: (string | null)[] };
  provenance: { file_sha256: string; pipeline_git_sha: string; started_at: string; finished_at: string; llm_calls: LlmCall[] };
}
