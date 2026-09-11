"use client";

import { FileText, Image as ImageIcon, Table as TableIcon } from "lucide-react";
import { DocumentSummary } from "@/lib/api";
import UploadDropzone from "./UploadDropzone";

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "baru saja";
  if (mins < 60) return `${mins} menit lalu`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} jam lalu`;
  return `${Math.floor(hrs / 24)} hari lalu`;
}

export default function Sidebar({
  documents,
  onIngested,
}: {
  documents: DocumentSummary[];
  onIngested: () => void;
}) {
  return (
    <aside className="flex h-full w-80 shrink-0 flex-col border-r border-line bg-paper-raised">
      <div className="border-b border-line px-5 py-5">
        <h1 className="font-serif text-lg font-semibold text-ink">Indeks Dokumen</h1>
        <p className="mt-1 text-xs text-ink-soft">
          Setiap jawaban asisten dirujuk balik ke sini.
        </p>
      </div>

      <div className="border-b border-line px-5 py-4">
        <UploadDropzone onIngested={onIngested} />
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {documents.length === 0 ? (
          <p className="text-sm text-ink-faint">
            Belum ada dokumen. Unggah satu untuk mulai bertanya.
          </p>
        ) : (
          <ul className="space-y-3">
            {documents.map((doc, i) => (
              <li key={doc.id} className="rounded-lg border border-line bg-paper px-3 py-3">
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 font-serif text-xs text-ink-faint">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink" title={doc.filename}>
                      {doc.filename}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-soft">
                      <span className="inline-flex items-center gap-1">
                        <FileText size={12} /> {doc.embedding_model}
                      </span>
                      {doc.vlm_enabled && (
                        <span className="inline-flex items-center gap-1 text-teal">
                          <ImageIcon size={12} /> VLM
                        </span>
                      )}
                      {doc.excel_tables > 0 && (
                        <span className="inline-flex items-center gap-1 text-teal">
                          <TableIcon size={12} />
                          {doc.excel_tables} tabel
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-ink-faint">{timeAgo(doc.created_at)}</p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-line px-5 py-3">
        <p className="flex items-center gap-1.5 text-xs text-ink-faint">
          <TableIcon size={12} />
          Teks, tabel, dan gambar diindeks terpisah per model embedding.
        </p>
      </div>
    </aside>
  );
}
