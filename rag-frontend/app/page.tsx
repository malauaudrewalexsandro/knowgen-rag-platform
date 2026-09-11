"use client";

import { useCallback, useEffect, useState } from "react";
import { DocumentSummary, listDocuments } from "@/lib/api";
import Sidebar from "@/components/Sidebar";
import ChatPanel from "@/components/ChatPanel";

export default function HomePage() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshDocuments = useCallback(async () => {
    try {
      const docs = await listDocuments();
      setDocuments(docs);
      setLoadError(null);
    } catch (e) {
      setLoadError(
        e instanceof Error
          ? `${e.message} — pastikan backend jalan di NEXT_PUBLIC_API_BASE_URL.`
          : "Gagal memuat daftar dokumen."
      );
    }
  }, []);

  useEffect(() => {
    refreshDocuments();
  }, [refreshDocuments]);

  return (
    <main className="flex h-screen bg-paper">
      <Sidebar documents={documents} onIngested={refreshDocuments} />
      <div className="flex flex-1 flex-col">
        {loadError && (
          <div className="border-b border-amber/40 bg-amber-soft px-8 py-2 text-xs text-ink">
            {loadError}
          </div>
        )}
        <ChatPanel hasDocuments={documents.length > 0} />
      </div>
    </main>
  );
}
