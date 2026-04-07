'use client';

// src/context/ProjectContext.tsx

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import type { Project, AuditResults, AuditStatus, Requirement } from '../types';
import {
  getProject,
  getRawAuditResults,
  transformAuditResults,
  getAuditStatus,
  getRequirements,
  ApiError,
} from '../lib/api';

interface ProjectContextValue {
  project: Project | null;
  auditResults: AuditResults | null;
  auditStatus: AuditStatus | null;
  requirements: Requirement[];
  loading: boolean;
  error: string | null;
  loadProject: (id: string) => Promise<void>;
  loadAuditResults: (id: string) => Promise<void>;
  loadRequirements: (id: string) => Promise<void>;
  setAuditStatus: (s: AuditStatus) => void;
  setAuditResults: (r: AuditResults | null) => void;
  clearError: () => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [project,      setProject]      = useState<Project | null>(null);
  const [auditResults, setAuditResults] = useState<AuditResults | null>(null);
  const [auditStatus,  setAuditStatus]  = useState<AuditStatus | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState<string | null>(null);

  const loadProject = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const p = await getProject(id);
      setProject(p);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : 'Failed to load project.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAuditResults = useCallback(async (id: string) => {
    try {
      const raw = await getRawAuditResults(id);
      const transformed = transformAuditResults(raw as Record<string, unknown>, id);
      setAuditResults(transformed);
    } catch (e) {
      // 404 = audit not run yet — expected, not an error
      if (e instanceof ApiError && e.isNotFound) return;
      const msg = e instanceof ApiError ? e.message : 'Failed to load audit results.';
      setError(msg);
    }
  }, []);

  const loadRequirements = useCallback(async (id: string) => {
    try {
      const reqs = await getRequirements(id);
      setRequirements(reqs);
    } catch (e) {
      // 404 = none extracted yet
      if (e instanceof ApiError && e.isNotFound) return;
      const msg = e instanceof ApiError ? e.message : 'Failed to load requirements.';
      setError(msg);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return (
    <ProjectContext.Provider
      value={{
        project,
        auditResults,
        auditStatus,
        requirements,
        loading,
        error,
        loadProject,
        loadAuditResults,
        loadRequirements,
        setAuditStatus,
        setAuditResults,
        clearError,
      }}
    >
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error('useProject must be used inside <ProjectProvider>');
  return ctx;
}