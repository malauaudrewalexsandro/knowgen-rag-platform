"use client";

import { useState } from "react";
import { ChevronDown, Download, Loader2 } from "lucide-react";
import { generateDocument, GenerateFormat } from "@/lib/api";

const FORMATS: { value: GenerateFormat; label: string }[] = [
  { value: "pdf", label: "PDF" },
  { value: "docx", label: "Word (.docx)" },
  { value: "pptx", label: "PowerPoint (.pptx)" },
  { value: "xlsx", label: "Excel (.xlsx)" },
];

export default function GenerateReportButton({ documentId }: { documentId: string }) {
  const [format, setFormat] = useState<GenerateFormat>("pdf");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setIsGenerating(true);
    setError(null);
    try {
      const { blob, filename } = await generateDocument(documentId, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal membuat laporan.");
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    // stopPropagation so clicking the picker doesn't trigger any click
    // handler the parent document row might have (e.g. "select document").
    <div className="mt-2 flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
      <div className="relative">
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as GenerateFormat)}
          disabled={isGenerating}
          className="appearance-none rounded-md border border-line bg-paper py-1 pl-2 pr-6 text-xs text-ink-soft focus:border-teal focus:outline-none disabled:opacity-50"
        >
          {FORMATS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
        <ChevronDown
          size={12}
          className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-ink-faint"
        />
      </div>

      <button
        type="button"
        onClick={handleGenerate}
        disabled={isGenerating}
        className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-teal transition-colors hover:border-teal disabled:opacity-50"
      >
        {isGenerating ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
        {isGenerating ? "Membuat…" : "Generate"}
      </button>

      {error && <p className="w-full text-[11px] text-red-700">{error}</p>}
    </div>
  );
}
