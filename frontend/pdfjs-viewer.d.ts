// src/types/pdfjs.d.ts
// Minimal type shims for pdfjs-dist so TypeScript doesn't complain.
// The package ships its own types in newer versions; this is only needed
// if your installed version doesn't include them.

declare module 'pdfjs-dist' {
  export const version: string;

  export const GlobalWorkerOptions: {
    workerSrc: string;
  };

  export interface PDFPageViewport {
    width: number;
    height: number;
  }

  export interface PDFRenderTask {
    promise: Promise<void>;
    cancel: () => void;
  }

  export interface PDFPageProxy {
    getViewport(options: { scale: number; rotation?: number }): PDFPageViewport;
    render(options: {
      canvasContext: CanvasRenderingContext2D;
      viewport: PDFPageViewport;
    }): PDFRenderTask;
  }

  export interface PDFDocumentProxy {
    numPages: number;
    getPage(pageNumber: number): Promise<PDFPageProxy>;
    destroy(): void;
  }

  export interface PDFDocumentLoadingTask {
    promise: Promise<PDFDocumentProxy>;
    destroy(): void;
  }

  export function getDocument(options: {
    url?: string;
    data?: Uint8Array;
    withCredentials?: boolean;
    password?: string;
  }): PDFDocumentLoadingTask;
}