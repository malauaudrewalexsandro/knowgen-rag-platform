"use client";

import { useRef, useState } from "react";
import { UploadCloud, Loader2 } from "lucide-react";
import { ingestDocument } from "@/lib/api";

export default function UploadDropzone({ onIngested }: { onIngested: () => void }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setIsUploading(true);
    setError(null);
    try {
      await ingestDocument(file, { vlm_enabled: false });
      onIngested();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal mengunggah dokumen.");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) handleFile(file);
        }}
        className={`w-full rounded-lg border border-dashed px-4 py-6 text-left transition-colors ${
          isDragging ? "border-teal bg-teal-soft" : "border-line hover:border-ink-faint"
        }`}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0 text-teal">
            {isUploading ? <Loader2 size={18} className="animate-spin" /> : <UploadCloud size={18} />}
          </div>
          <div>
            <p className="text-sm font-medium text-ink">
              {isUploading ? "Mengunggah dan memproses…" : "Tambah dokumen"}
            </p>
            <p className="mt-0.5 text-xs text-ink-soft">
              PDF, DOCX, PPTX, XLSX, atau CSV. Seret ke sini atau klik untuk memilih.
            </p>
          </div>
        </div>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.pptx,.xlsx,.xls,.csv"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
          e.target.value = "";
        }}
      />
      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
    </div>
  );
}
