'use client';

// components/TracePdfViewerContent.tsx
//
// Renders ALL pages of a PDF document using pdfjs-dist, then scrolls to the
// target page on mount and draws a yellow highlight over the bbox span.
//
// Coordinate system note
// ──────────────────────
// PyMuPDF (fitz) — which your FastAPI backend uses — stores bbox as:
//   [x0, y0, x1, y1]  with origin = TOP-LEFT of the page, y increases DOWN.
// This matches the HTML canvas coordinate system exactly, so NO y-flip is needed.
// The previously wrong code was applying a "PDF standard" y-flip that is only
// correct for PDF spec coordinates (origin = bottom-left), not for fitz rects.
//
// Full-document rendering
// ───────────────────────
// Instead of rendering only one page, we render every page sequentially.
// Each page gets its own <canvas>. The page matching `pageNumber` is given a
// stable DOM id so we can call scrollIntoView on it after rendering finishes.

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { TracePdfViewerProps } from '@/TracePdfViewer';

// ── Worker setup ──────────────────────────────────────────────────────────────

import * as pdfjs from 'pdfjs-dist';

if (typeof window !== 'undefined') {
  pdfjs.GlobalWorkerOptions.workerSrc =
    `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
}

// ── Types ─────────────────────────────────────────────────────────────────────

/** Per-page render metadata stored after each page is drawn. */
interface PageMeta {
  pageIndex: number;  // 0-based
  cssW: number;
  cssH: number;
  /** PDF page width in PDF user-space units (unscaled, from the base viewport) */
  pageWidthPt: number;
  /** PDF page height in PDF user-space units */
  pageHeightPt: number;
}

// ── Stable page canvas id ──────────────────────────────────────────────────────
function pageCanvasId(pageIndex: number, uid: string) {
  return `pdf-page-${uid}-${pageIndex}`;
}
function pageWrapId(pageIndex: number, uid: string) {
  return `pdf-pagewrap-${uid}-${pageIndex}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function TracePdfViewerContent({
  fileUrl,
  pageNumber,
  bbox,
}: TracePdfViewerProps) {
  // Unique id per component instance so multiple viewers on the same page
  
  const uid = useRef(`${Date.now()}-${Math.random().toString(36).slice(2)}`).current;

  const containerRef    = useRef<HTMLDivElement>(null);
  const scrollRef       = useRef<HTMLDivElement>(null);

  const [containerWidth, setContainerWidth] = useState(0);
  const [pageMetas,      setPageMetas]      = useState<PageMeta[]>([]);
  const [totalPages,     setTotalPages]     = useState(0);
  const [loadingState,   setLoadingState]   = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [errorMsg,       setErrorMsg]       = useState<string | null>(null);

  // ── Measure container width ────────────────────────────────────────────────
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setContainerWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ── Render all PDF pages ───────────────────────────────────────────────────
  useEffect(() => {
    if (containerWidth < 48 || !fileUrl) return;

    let cancelled = false;

    const renderAll = async () => {
      setLoadingState('loading');
      setErrorMsg(null);
      setPageMetas([]);

      try {
        // Available inner width after padding (16px each side)
        const innerW = Math.max(containerWidth - 32, 200);

        const loadingTask = pdfjs.getDocument({ url: fileUrl, withCredentials: true });
        const pdf = await loadingTask.promise;
        if (cancelled) return;

        const total = pdf.numPages;
        setTotalPages(total);

        const metas: PageMeta[] = [];

        for (let i = 1; i <= total; i++) {
          if (cancelled) return;

          const page     = await pdf.getPage(i);
          const baseVp   = page.getViewport({ scale: 1 });
          const scale    = innerW / baseVp.width;
          const viewport = page.getViewport({ scale });

          const cssW = viewport.width;
          const cssH = viewport.height;

          const canvas = document.getElementById(
            pageCanvasId(i - 1, uid),
          ) as HTMLCanvasElement | null;

          if (!canvas || cancelled) continue;

          const ctx = canvas.getContext('2d');
          if (!ctx) continue;

          // HiDPI: render at physical resolution for sharpness on retina screens
          const dpr = Math.min(window.devicePixelRatio ?? 1, 2);
          canvas.width  = Math.round(cssW * dpr);
          canvas.height = Math.round(cssH * dpr);
          canvas.style.width  = `${cssW}px`;
          canvas.style.height = `${cssH}px`;
          ctx.scale(dpr, dpr);

          await page.render({ canvasContext: ctx, viewport }).promise;
          if (cancelled) return;

          const meta: PageMeta = {
            pageIndex: i - 1,
            cssW,
            cssH,
            pageWidthPt:  baseVp.width,
            pageHeightPt: baseVp.height,
          };
          metas.push(meta);

          // Update state incrementally so pages appear as they render
          setPageMetas([...metas]);
        }

        if (!cancelled) setLoadingState('done');
      } catch (err: unknown) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to render PDF';
          console.error('[TracePdfViewer]', err);
          setErrorMsg(msg);
          setLoadingState('error');
        }
      }
    };

    void renderAll();
    return () => { cancelled = true; };
  }, [fileUrl, containerWidth, uid]);

  // ── Scroll to target page once all pages are done ─────────────────────────
  useEffect(() => {
    if (loadingState !== 'done') return;

    // Small rAF delay so the DOM has painted before we scroll
    const raf = requestAnimationFrame(() => {
      const targetIndex = Math.max(1, Math.min(pageNumber, totalPages)) - 1;
      const wrap = document.getElementById(pageWrapId(targetIndex, uid));
      if (wrap) {
        wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [loadingState, pageNumber, totalPages, uid]);

  // ── Compute highlight style for the target page ────────────────────────────
  //
  // PyMuPDF (fitz) bbox coordinates:
  //   x0, y0 = TOP-LEFT corner  (y0 is distance from TOP of page)
  //   x1, y1 = BOTTOM-RIGHT corner
  //   y increases DOWNWARD
  //
  // HTML Canvas coordinate system:
  //   origin = top-left, y increases downward
  //
  // Therefore: NO y-flip needed. Just scale from PDF units to CSS pixels.
  //
  const targetPageMeta = useMemo(() => {
    if (!pageMetas.length) return null;
    const idx = Math.max(1, Math.min(pageNumber, totalPages)) - 1;
    return pageMetas.find((m) => m.pageIndex === idx) ?? null;
  }, [pageMetas, pageNumber, totalPages]);

  const highlightStyle = useMemo<React.CSSProperties | null>(() => {
    if (!bbox || bbox.length < 4 || !targetPageMeta) return null;

    const { cssW, pageWidthPt } = targetPageMeta;
    const [x0, y0, x1, y1] = bbox;

    // Scale factor: CSS pixels per PDF user-space unit
    const scale = cssW / pageWidthPt;

    // Direct mapping — fitz uses top-left origin just like CSS
    const cssLeft   = x0 * scale;
    const cssTop    = y0 * scale;
    const cssWidth  = (x1 - x0) * scale;
    const cssHeight = (y1 - y0) * scale;

    return {
      position:     'absolute',
      top:          `${cssTop}px`,
      left:         `${cssLeft}px`,
      width:        `${cssWidth}px`,
      height:       `${cssHeight}px`,
      background:   'rgba(253, 224, 71, 0.45)',
      borderBottom: '2px solid rgba(202, 138, 4, 0.85)',
      borderRadius: '2px',
      pointerEvents: 'none',
      // Pulse animation to draw attention on first render
      animation: 'highlightPulse 0.6s ease',
    };
  }, [bbox, targetPageMeta]);

  // ── Error state ────────────────────────────────────────────────────────────
  if (loadingState === 'error') {
    return (
      <div style={outerContainerStyle}>
        <div style={{ padding: '48px 24px', textAlign: 'center', fontSize: 13, color: '#DC2626', lineHeight: 1.6 }}>
          ⚠ {errorMsg}
          <br />
          <span style={{ fontSize: 11, color: '#A1A1AA', marginTop: 6, display: 'block' }}>
            Ensure the FastAPI server is running and CORS is enabled for localhost:3000.
          </span>
        </div>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  const targetIdx = Math.max(1, Math.min(pageNumber, totalPages || pageNumber)) - 1;

  return (
    <div style={outerContainerStyle}>
      {/* Highlight pulse keyframe injected once */}
      <style>{`
        @keyframes highlightPulse {
          0%   { background: rgba(253, 224, 71, 0.75); }
          100% { background: rgba(253, 224, 71, 0.45); }
        }
      `}</style>

      {/* Top status bar */}
      <div style={statusBarStyle}>
        {loadingState === 'loading' ? (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</span>
            Rendering…{' '}
            {pageMetas.length > 0 && (
              <span style={{ color: 'var(--t3)' }}>({pageMetas.length} / {totalPages} pages)</span>
            )}
          </span>
        ) : loadingState === 'done' ? (
          <span style={{ color: 'var(--full)', fontWeight: 600 }}>
            ✓ {totalPages} page{totalPages !== 1 ? 's' : ''} · Showing p.{pageNumber}
            {bbox ? ' · Highlight active' : ''}
          </span>
        ) : (
          <span style={{ color: 'var(--t3)' }}>Loading…</span>
        )}
      </div>

      {/* Measure ref — invisible, just for container width */}
      <div ref={containerRef} style={{ width: '100%', height: 0, overflow: 'hidden' }} aria-hidden />

      {/* Scroll container with all pages */}
      <div ref={scrollRef} style={scrollContainerStyle}>
        {/* Placeholder canvases for every page (rendered as pages load) */}
        {Array.from({ length: Math.max(totalPages, 1) }, (_, i) => {
          const meta     = pageMetas.find((m) => m.pageIndex === i);
          const isTarget = i === targetIdx;

          return (
            <div
              key={i}
              id={pageWrapId(i, uid)}
              style={{
                display:        'flex',
                justifyContent: 'center',
                padding:        '12px 16px',
                background:     '#E8E7E2',
                // Visually separate each page with a gap
                borderBottom:   i < (totalPages - 1) ? '8px solid #D5D3CC' : 'none',
              }}
            >
              {/* Page number label */}
              <div style={{ position: 'relative' }}>
                <div style={pageLabelStyle(isTarget)}>
                  {i + 1}
                  {isTarget && bbox && ' ◀'}
                </div>

                {/* The canvas — sized by the render effect above */}
                <div
                  style={{
                    position:  'relative',
                    display:   'inline-block',
                    boxShadow: '0 2px 12px rgba(0,0,0,.18)',
                    // Min size so layout doesn't collapse before render
                    minWidth:  meta ? `${meta.cssW}px` : 200,
                    minHeight: meta ? `${meta.cssH}px` : 100,
                    background: '#fff',
                  }}
                >
                  <canvas
                    id={pageCanvasId(i, uid)}
                    style={{ display: 'block' }}
                  />

                  {/* Yellow highlight — only on the target page */}
                  {isTarget && meta && highlightStyle && (
                    <div style={highlightStyle} />
                  )}

                  {/* Loading shimmer while this page hasn't rendered yet */}
                  {!meta && (
                    <div style={{
                      position: 'absolute', inset: 0,
                      background: 'linear-gradient(90deg, #e8e7e2 25%, #f0efea 50%, #e8e7e2 75%)',
                      backgroundSize: '200% 100%',
                      animation: 'shimmer 1.4s infinite',
                    }} />
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Static styles ─────────────────────────────────────────────────────────────

const outerContainerStyle: React.CSSProperties = {
  width:          '100%',
  border:         '1px solid var(--border)',
  borderRadius:   8,
  overflow:       'hidden',
  background:     '#E8E7E2',
  display:        'flex',
  flexDirection:  'column',
};

const statusBarStyle: React.CSSProperties = {
  padding:        '6px 14px',
  background:     '#F4F3EF',
  borderBottom:   '1px solid var(--border)',
  fontSize:       11,
  color:          'var(--t2)',
  fontFamily:     'var(--font-mono), monospace',
  display:        'flex',
  alignItems:     'center',
  gap:            8,
  flexShrink:     0,
};

const scrollContainerStyle: React.CSSProperties = {
  flex:           1,
  overflowY:      'auto',
  maxHeight:      '72vh',
  scrollbarWidth: 'thin',
  scrollbarColor: 'rgba(0,0,0,.18) transparent',
};

function pageLabelStyle(isTarget: boolean): React.CSSProperties {
  return {
    position:   'absolute',
    top:        -22,
    left:       0,
    fontSize:   9,
    fontFamily: 'var(--font-mono), monospace',
    fontWeight: 700,
    color:      isTarget ? '#CA8A04' : '#A1A1AA',
    letterSpacing: '.05em',
    textTransform: 'uppercase',
    userSelect: 'none',
  };
}