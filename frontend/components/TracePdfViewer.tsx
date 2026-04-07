'use client';

// components/TracePdfViewer.tsx
// Thin SSR-disabled wrapper. All rendering logic lives in TracePdfViewerContent.

import dynamic from 'next/dynamic';
import React from 'react';

const TracePdfViewerContent = dynamic(
  () => import('./TracePdfViewerContent'),
  {
    ssr: false,
    loading: () => (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: 200, background: '#F4F3EF', borderRadius: 8,
        fontSize: 13, color: '#A1A1AA',
      }}>
        Initialising PDF engine…
      </div>
    ),
  }
);

export interface TracePdfViewerProps {
  /** Absolute URL to the PDF file served by the FastAPI backend */
  fileUrl: string;
  /** 1-based page number that contains the highlighted text */
  pageNumber: number;
  /**
   * Bounding box [x0, y0, x1, y1] in PyMuPDF / fitz coordinates:
   *   - origin = top-left of the page
   *   - x increases right, y increases DOWN
   * This matches fitz.Rect directly — no y-flip needed.
   */
  bbox?: number[] | null;
}

export default function TracePdfViewer(props: TracePdfViewerProps) {
  return <TracePdfViewerContent {...props} />;
}