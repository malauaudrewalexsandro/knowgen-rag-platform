export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export interface RetrievedChunk {
  id: string;
  score: number;
  document_id?: string;
  chunk_type?: string;
  content?: string;
  page?: number | null;
  table_name?: string;
  sql?: string;
}

export interface ChatResponse {
  reply: string;
  retrieved_chunks: RetrievedChunk[];
  model_used: string;
  // Relative path (e.g. "/generate/chart/xyz.png") when the assistant
  // called the generate_chart tool for this turn — see app/core/rag_chain.py.
  chart_url?: string | null;
  // Relative path (e.g. "/generate/download/xyz.pdf?download_name=...")
  // when the assistant called the clone_document tool for this turn.
  file_url?: string | null;
  file_name?: string | null;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  embedding_model: string;
  embedding_dims: number;
  collection_key: string;
  vlm_enabled: boolean;
  created_at: string;
  excel_tables: number;
}

export interface IngestResponse {
  document_id: string;
  filename: string;
  collection_key: string;
  text_chunks: number;
  table_chunks: number;
  image_chunks: number;
  excel_tables: number;
}

export async function sendChat(
  messages: { role: string; content: string }[],
  opts?: { llm_model?: string; embedding_model?: string; embedding_dims?: number; top_k?: number }
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, ...opts }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Chat request failed (${res.status}): ${detail}`);
  }
  return res.json();
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch(`${API_BASE}/documents`);
  if (!res.ok) throw new Error(`Failed to load documents (${res.status})`);
  return res.json();
}

export async function ingestDocument(
  file: File,
  opts?: { embedding_model?: string; vlm_enabled?: boolean; vlm_model?: string }
): Promise<IngestResponse> {
  const form = new FormData();
  form.append("file", file);
  if (opts?.embedding_model) form.append("embedding_model", opts.embedding_model);
  if (opts?.vlm_enabled !== undefined) form.append("vlm_enabled", String(opts.vlm_enabled));
  if (opts?.vlm_model) form.append("vlm_model", opts.vlm_model);

  const res = await fetch(`${API_BASE}/documents/ingest`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Ingest failed (${res.status}): ${detail}`);
  }
  return res.json();
}

export type GenerateFormat = "pdf" | "docx" | "pptx" | "xlsx";

/**
 * Calls POST /generate/document and returns the generated file as a Blob
 * plus the filename the backend suggested (from Content-Disposition —
 * requires the backend's CORS config to expose_headers that header, see
 * app/main.py). Caller is responsible for triggering the actual download.
 */
export async function generateDocument(
  documentId: string,
  format: GenerateFormat,
  opts?: { title?: string; llm_model?: string }
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${API_BASE}/generate/document`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, format, ...opts }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Generate failed (${res.status}): ${detail}`);
  }

  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `report.${format}`;
  return { blob, filename };
}
