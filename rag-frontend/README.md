# RAG Frontend

Next.js interface for the `rag-backend` project. Two-pane workspace: a
document index on the left, a chat on the right where every answer carries
numbered citation marks linking back to the exact chunk it came from.

## Design notes

- **Palette**: cool paper white (`#F1F2ED`) + ink navy text, amber accent for
  citations (index-card stamp feel), teal for AI/system elements.
- **Type**: Source Serif 4 for headings/titles (printed-page feel), Inter for
  UI and chat text.
- **Citations**: assistant replies end with small numbered tags — hover or
  tap one to see the exact chunk (and page, if known) it was grounded in.

## Setup (from a blank folder, same idea as the backend)

```bash
npm install
```

```bash
cp .env.local.example .env.local
```

Open `.env.local` and confirm `NEXT_PUBLIC_API_BASE_URL` points at your
running `rag-backend` (default `http://localhost:8000` — matches the
backend's default port, no change needed if you followed that README).

```bash
npm run dev
```

Open `http://localhost:3000`.

**Make sure `rag-backend` is running first** (`uvicorn app.main:app --reload
--port 8000` in the other project) — this frontend has no functionality of
its own without it; every action (listing documents, uploading, chatting)
calls the backend directly.

## What each piece does

- `app/page.tsx` — wires the sidebar and chat panel together, loads the
  document list on mount.
- `components/Sidebar.tsx` — document index + upload dropzone.
- `components/UploadDropzone.tsx` — drag-and-drop or click-to-browse upload,
  calls `POST /documents/ingest` on the backend.
- `components/ChatPanel.tsx` — message list + input, calls `POST /chat`.
- `components/MessageBubble.tsx` — renders assistant replies with numbered
  citation marks; each mark is a `RetrievedChunk` from the backend's
  response, shown in a small popover on hover/click.
- `lib/api.ts` — the only file that talks to the backend; every request
  shape matches `rag-backend`'s Pydantic schemas exactly.

## Extending

- **VLM toggle at upload time**: `UploadDropzone` currently always sends
  `vlm_enabled: false`. Add a checkbox and pass it through — the backend
  already supports it.
- **Model picker**: `sendChat` in `lib/api.ts` accepts `llm_model` /
  `embedding_model` overrides — wire a dropdown in the header if you want
  per-conversation model switching from the UI.
- **Streaming**: the backend currently returns one full reply per request.
  If you add SSE/streaming to `/chat` later, `ChatPanel.tsx` is the only
  place that needs to change to consume it token-by-token.
