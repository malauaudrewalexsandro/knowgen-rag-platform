"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { API_BASE, RetrievedChunk } from "@/lib/api";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: RetrievedChunk[];
  chartUrl?: string | null;
  fileUrl?: string | null;
  fileName?: string | null;
}

function CitationPopover({ index, chunk }: { index: number; chunk: RetrievedChunk }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block">
      <span
        className="citation-mark"
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        {index}
      </span>
      {open && (
        <span className="absolute bottom-full left-1/2 z-10 mb-2 w-72 -translate-x-1/2 rounded-lg border border-line bg-paper-raised p-3 text-left shadow-card">
          <span className="mb-1 flex items-center justify-between text-xs font-medium text-ink-soft">
            <span className="uppercase tracking-wide">
              {chunk.chunk_type === "sql_result"
                ? "Kueri SQL"
                : chunk.chunk_type === "chart_result"
                ? "Chart"
                : chunk.chunk_type === "clone_result"
                ? "Dokumen hasil clone"
                : chunk.chunk_type === "table_schema"
                ? "Tabel spreadsheet"
                : chunk.chunk_type ?? "text"}
            </span>
            {chunk.page != null && <span>hal. {chunk.page}</span>}
          </span>
          {chunk.sql && (
            <code className="mb-1 block whitespace-pre-wrap break-words rounded bg-ink/5 px-1.5 py-1 text-xs text-ink">
              {chunk.sql}
            </code>
          )}
          <span className="block text-sm leading-snug text-ink">
            {(chunk.content ?? "").slice(0, 220)}
            {(chunk.content?.length ?? 0) > 220 ? "…" : ""}
          </span>
        </span>
      )}
    </span>
  );
}

export default function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-lg bg-ink px-4 py-2.5 text-[0.95rem] leading-relaxed text-paper">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[75%] rounded-lg border-l-2 border-teal bg-paper-raised px-4 py-3 shadow-card">
        <p className="text-[0.95rem] leading-relaxed text-ink">
          {message.content}
          {message.sources?.map((chunk, i) => (
            <CitationPopover key={chunk.id} index={i + 1} chunk={chunk} />
          ))}
        </p>

        {message.chartUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`${API_BASE}${message.chartUrl}`}
            alt="Chart yang dihasilkan"
            className="mt-3 max-w-full rounded-md border border-line"
          />
        )}

        {message.fileUrl && (
          <a
            href={`${API_BASE}${message.fileUrl}`}
            download={message.fileName ?? undefined}
            className="mt-3 inline-flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-xs font-medium text-teal transition-colors hover:border-teal"
          >
            <Download size={13} />
            {message.fileName ?? "Download dokumen"}
          </a>
        )}
      </div>
    </div>
  );
}
