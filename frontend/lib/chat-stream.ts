// SSE + REST chat client (kept separate from `api.ts` to avoid barrel init / HMR edge cases).

import type { ChatMessage } from '@/types';
import { API_BASE as BASE } from './api-base';

export interface RichCitation {
  citation_index: number;
  vendor_name: string;
  vendor_document_id: number;
  section_title?: string;
  page_number?: number;
  text: string;
}

export interface MultiVendorChatResponse {
  reply: string;
  citations: RichCitation[];
  vendors_searched: string[];
}

export type SSEEvent =
  | { type: 'vendors'; vendors: string[] }
  | { type: 'token'; token: string }
  | { type: 'citations'; citations: RichCitation[] }
  | { type: 'done' }
  | { type: 'error'; message: string };

export interface StreamChatCallbacks {
  onVendors?: (vendors: string[]) => void;
  onToken: (token: string, accumulated: string) => void;
  onCitations: (citations: RichCitation[]) => void;
  onDone: (fullReply: string, citations: RichCitation[]) => void;
  onError?: (message: string) => void;
}

/**
 * Stream a multi-vendor chat message via SSE.
 * Returns an AbortController so the caller can cancel mid-stream.
 */
export function streamChatMessage(
  projectId: string,
  payload: {
    message: string;
    history: ChatMessage[];
    documentIds?: number[];
  },
  callbacks: StreamChatCallbacks,
): AbortController {
  const controller = new AbortController();

  (async () => {
    let accumulated = '';
    let finalCitations: RichCitation[] = [];

    try {
      const res = await fetch(`${BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: Number(projectId),
          document_ids: payload.documentIds ?? [],
          message: payload.message,
          history: payload.history,
        }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => res.statusText);
        callbacks.onError?.(text);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event: SSEEvent;
          try {
            event = JSON.parse(raw);
          } catch {
            continue;
          }

          switch (event.type) {
            case 'vendors':
              callbacks.onVendors?.(event.vendors);
              break;
            case 'token':
              accumulated += event.token;
              callbacks.onToken(event.token, accumulated);
              break;
            case 'citations':
              finalCitations = event.citations;
              callbacks.onCitations(event.citations);
              break;
            case 'done':
              callbacks.onDone(accumulated, finalCitations);
              return;
            case 'error':
              callbacks.onError?.(event.message);
              return;
          }
        }
      }

      callbacks.onDone(accumulated, finalCitations);
    } catch (err: unknown) {
      if ((err as Error).name !== 'AbortError') {
        callbacks.onError?.((err as Error).message ?? 'Stream error');
      }
    }
  })();

  return controller;
}

/** Non-streaming fallback when SSE is unavailable. */
export async function sendChatMessage(
  projectId: string,
  data: {
    message: string;
    history: ChatMessage[];
    documentIds?: number[];
  },
): Promise<{ reply: string; citations: RichCitation[]; vendors_searched: string[] }> {
  const res = await fetch(`${BASE}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: Number(projectId),
      document_ids: data.documentIds ?? [],
      message: data.message,
      history: data.history,
    }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? res.statusText);
  }

  return res.json();
}
