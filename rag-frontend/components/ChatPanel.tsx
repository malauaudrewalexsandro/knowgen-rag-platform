"use client";

import { useRef, useState } from "react";
import { Send, Loader2 } from "lucide-react";
import { sendChat } from "@/lib/api";
import MessageBubble, { ChatMessage } from "./MessageBubble";

export default function ChatPanel({ hasDocuments }: { hasDocuments: boolean }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  async function handleSend() {
    const question = input.trim();
    if (!question || isSending) return;

    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: question }];
    setMessages(nextMessages);
    setInput("");
    setIsSending(true);
    setError(null);

    try {
      const res = await sendChat(nextMessages.map(({ role, content }) => ({ role, content })));
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.reply, sources: res.retrieved_chunks },
      ]);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Terjadi kesalahan saat menghubungi asisten.");
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="flex h-full flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-line px-8 py-5">
        <div>
          <h2 className="font-serif text-lg font-semibold text-ink">Tanya Dokumen</h2>
          <p className="mt-0.5 text-xs text-ink-soft">
            Jawaban dirujuk ke sumbernya — klik angka kecil untuk melihat kutipan.
          </p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-8 py-6">
        {messages.length === 0 ? (
          <div className="mx-auto mt-16 max-w-md text-center">
            <p className="font-serif text-xl text-ink">
              {hasDocuments ? "Mulai dengan sebuah pertanyaan." : "Belum ada dokumen terindeks."}
            </p>
            <p className="mt-2 text-sm text-ink-soft">
              {hasDocuments
                ? "Asisten menjawab hanya dari dokumen yang sudah diunggah, lengkap dengan rujukannya."
                : "Unggah dokumen lewat panel kiri, lalu ajukan pertanyaan di sini."}
            </p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-4">
            {messages.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))}
            {isSending && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-lg border-l-2 border-teal bg-paper-raised px-4 py-3 text-sm text-ink-soft shadow-card">
                  <Loader2 size={14} className="animate-spin" />
                  Menelusuri dokumen…
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="border-t border-line px-8 py-5">
        {error && <p className="mx-auto mb-2 max-w-2xl text-xs text-red-700">{error}</p>}
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Tanyakan sesuatu tentang dokumen Anda…"
            rows={1}
            className="max-h-32 flex-1 resize-none rounded-lg border border-line bg-paper-raised px-4 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-teal focus:outline-none"
          />
          <button
            onClick={handleSend}
            disabled={isSending || !input.trim()}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-ink text-paper transition-opacity disabled:opacity-30"
            aria-label="Kirim pertanyaan"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
