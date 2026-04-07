'use client';

// src/context/ToastContext.tsx
// Global toast notification system. Wrap app with <ToastProvider>.
// Use useToast() anywhere to show success/error/info toasts.

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
} from 'react';
import type { ToastMessage } from '../types';

interface ToastContextValue {
  showToast: (message: string, type?: ToastMessage['type']) => void;
  showSuccess: (message: string) => void;
  showError: (message: string) => void;
  showInfo: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const timerRefs = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timerRefs.current.get(id);
    if (timer) { clearTimeout(timer); timerRefs.current.delete(id); }
  }, []);

  const showToast = useCallback((message: string, type: ToastMessage['type'] = 'info') => {
    const id = `toast-${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev.slice(-4), { id, message, type }]); // keep max 5
    const timer = setTimeout(() => dismiss(id), 4000);
    timerRefs.current.set(id, timer);
  }, [dismiss]);

  useEffect(() => {
    const map = timerRefs.current;
    return () => { map.forEach(clearTimeout); };
  }, []);

  const showSuccess = useCallback((m: string) => showToast(m, 'success'), [showToast]);
  const showError   = useCallback((m: string) => showToast(m, 'error'),   [showToast]);
  const showInfo    = useCallback((m: string) => showToast(m, 'info'),    [showToast]);

  const ICONS: Record<ToastMessage['type'], string> = {
    success: '✓',
    error:   '✕',
    warning: '⚠',
    info:    'i',
  };

  const COLORS: Record<ToastMessage['type'], { bg: string; icon: string }> = {
    success: { bg: '#1C1E26', icon: '#10B981' },
    error:   { bg: '#1C1E26', icon: '#EF4444' },
    warning: { bg: '#1C1E26', icon: '#F59E0B' },
    info:    { bg: '#1C1E26', icon: '#5DD0C8' },
  };

  return (
    <ToastContext.Provider value={{ showToast, showSuccess, showError, showInfo }}>
      {children}

      {/* Toast stack — bottom right */}
      <div className="toast-container">
        {toasts.map((t) => {
          const c = COLORS[t.type];
          return (
            <div
              key={t.id}
              className={`toast-item ${t.type}`}
              style={{
                background: c.bg,
                color: 'white',
                padding: '10px 16px',
                borderRadius: 12,
                fontSize: 13,
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                boxShadow: '0 4px 16px rgba(0,0,0,.3)',
                pointerEvents: 'all',
                maxWidth: 380,
                lineHeight: 1.4,
              }}
            >
              <span
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: '50%',
                  background: c.icon,
                  color: '#1C1E26',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 10,
                  fontWeight: 700,
                  flexShrink: 0,
                }}
              >
                {ICONS[t.type]}
              </span>
              <span style={{ flex: 1 }}>{t.message}</span>
              <button
                onClick={() => dismiss(t.id)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'rgba(255,255,255,.45)',
                  cursor: 'pointer',
                  fontSize: 14,
                  padding: '0 2px',
                  lineHeight: 1,
                }}
              >
                ✕
              </button>
              {/* [MOTION] progress drain bar */}
              <div className="toast-drain" />
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}