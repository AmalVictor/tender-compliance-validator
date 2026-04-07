'use client';

import React, { useMemo, useState } from 'react';
import type { RiskFinding, RiskHeatmapCell, RiskSeverity } from '../types';

interface RiskHeatmapProps {
    heatmap: RiskHeatmapCell[];
    risks: RiskFinding[];
    onDeepDive?: (reqId?: string) => void;
}



const SEV_COLOR: Record<RiskSeverity, string> = {
    Critical: 'var(--crit)',
    High: 'var(--high)',
    Medium: 'var(--med)',
    Low: 'var(--low)',
};

const SEV_BG: Record<RiskSeverity, string> = {
    Critical: '#FECACA',
    High: '#FED7AA',
    Medium: '#FEF08A',
    Low: '#BBF7D0',
};

const SEV_ABBR: Record<RiskSeverity, string> = {
    Critical: 'C',
    High: 'H',
    Medium: 'M',
    Low: 'L',
};

const SEV_ORDER: Record<RiskSeverity, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };

// ── Which backend risk_type values belong to each heatmap column ──────────────
// Backend enum (database.py): liability_cap | scope_creep | price_change |
//   obligation_weakening | exit_clause | vague_commitment
// We also cover legacy/alternative spellings defensively.

const COL_TYPES: Record<string, string[]> = {
    liability_cap: ['liability_cap'],
    price_scope: ['price_change', 'scope_creep', 'price_risk'],
    obligation: ['obligation_weakening', 'vague_commitment'],
    ip_data: ['data_privacy', 'ip_ownership'],
    exit: ['exit_clause', 'termination'],
};

// ── Shared th style ───────────────────────────────────────────────────────────
const TH: React.CSSProperties = {
    textAlign: 'center',
    padding: '10px 14px',
    fontSize: '10px',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '.06em',
    color: 'var(--t3)',
    borderRight: '1px solid rgba(15,17,23,.06)',
    borderBottom: '1px solid var(--border)',
    background: '#FAFAF8',
    whiteSpace: 'nowrap',
};

// ── Sub-component: single heatmap cell ────────────────────────────────────────

function HeatCell({
    severity,
    count,
    onClick,
}: {
    severity: RiskSeverity | null;
    count: number;
    onClick: () => void;
}) {
    if (!severity) {
        return (
            <td style={{
                textAlign: 'center',
                padding: '14px 10px',
                background: '#F4F4F5',
                borderRight: '1px solid var(--border)',
                borderBottom: '1px solid var(--border)',
            }}>
                <span style={{ fontFamily: 'var(--fm)', fontSize: '18px', color: '#A1A1AA' }}>—</span>
            </td>
        );
    }

    return (
        <td
            style={{
                textAlign: 'center',
                padding: '14px 10px',
                background: SEV_BG[severity],
                borderRight: '1px solid var(--border)',
                borderBottom: '1px solid var(--border)',
                cursor: 'pointer',
                transition: 'filter .12s',
            }}
            onClick={onClick}
            onMouseEnter={e => (e.currentTarget.style.filter = 'brightness(0.93)')}
            onMouseLeave={e => (e.currentTarget.style.filter = '')}
        >
            <div style={{ fontFamily: 'var(--fm)', fontSize: '22px', fontWeight: 700, color: SEV_COLOR[severity], lineHeight: 1 }}>
                {count}
            </div>
            <div style={{ fontSize: '10px', fontWeight: 700, color: SEV_COLOR[severity], marginTop: '3px', opacity: 0.9 }}>
                {severity}
            </div>
        </td>
    );
}

// ── Sub-component: slide-in risk detail drawer ────────────────────────────────

function RiskDrawer({
    risk,
    open,
    onClose,
}: {
    risk: RiskFinding | null;
    open: boolean;
    onClose: () => void;
}) {
    if (!risk) return null;
    const page = risk.page ?? risk.page_number ?? 0;

    return (
        <>
            <div className={`drawer-overlay ${open ? 'open' : ''}`} onClick={onClose} />
            <div
                className={`risk-drawer ${open ? 'open' : ''}`}
                style={{
                    // [MOTION] upgrade to spring easing
                    transition: 'transform .30s cubic-bezier(0.34,1.4,0.64,1)',
                }}
            >
                <div className="rd-head">
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                            <span
                                className="bd"
                                style={{ background: SEV_BG[risk.severity], color: SEV_COLOR[risk.severity], fontSize: '10px', fontWeight: 700, textTransform: 'uppercase' }}
                            >
                                {risk.severity} Risk
                            </span>
                            <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--t2)' }}>{risk.vendor_name}</span>
                        </div>
                        <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--t1)', lineHeight: 1.35 }}>
                            "{risk.phrase}"
                        </div>
                        {(risk.section_ref || page > 0) && (
                            <div style={{ fontSize: '11px', color: 'var(--ac)', fontFamily: 'var(--fm)', marginTop: '6px' }}>
                                {[risk.section_ref, page > 0 ? `p.${page}` : ''].filter(Boolean).join(' · ')}
                            </div>
                        )}
                    </div>
                    <button className="btn btn-icon btn-g" onClick={onClose}>✕</button>
                </div>

                <div className="rd-body">
                    <div className="rd-field">
                        <div className="rd-field-label">Risk Category</div>
                        <div className="rd-field-val" style={{ fontSize: '12px' }}>
                            {(risk.risk_type ?? '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                        </div>
                    </div>

                    <div className="rd-field">
                        <div className="rd-field-label">AI Impact Analysis</div>
                        <div className="rd-field-val">{risk.impact || 'No analysis available.'}</div>
                    </div>

                    {risk.recommended_action && (
                        <div className="ai-box">
                            <div className="ai-head">
                                <div className="ai-spark">✦</div>
                                Recommended Action
                            </div>
                            <div className="ai-body-txt">{risk.recommended_action}</div>
                            <div className="ai-foot">
                                <span>{risk.confirmed_by_llm ? '✓ LLM CONFIRMED' : 'PATTERN MATCH'}</span>
                                {risk.rfp_clause_ref && <span>RFP: {risk.rfp_clause_ref}</span>}
                            </div>
                        </div>
                    )}

                </div>
            </div>
        </>
    );
}

// ── Sub-component: single risk finding card ───────────────────────────────────

function RiskCard({
    risk,
    isLast,
    onOpen,
    onDeepDive,
}: {
    risk: RiskFinding;
    isLast: boolean;
    onOpen: () => void;
    onDeepDive?: (reqId?: string) => void;
}) {
    const page = risk.page ?? risk.page_number ?? 0;
    const categoryLabel = (risk.risk_type ?? '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());

    return (
        <div
            style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '14px',
                padding: '14px 20px',
                borderBottom: isLast ? 'none' : '1px solid var(--border)',
                transition: 'background .12s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = '#FAFAF8')}
            onMouseLeave={e => (e.currentTarget.style.background = '')}
        >
            {/* Left severity badge */}
            <div style={{
                width: '28px',
                height: '28px',
                borderRadius: '7px',
                background: SEV_BG[risk.severity],
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                marginTop: '1px',
            }}>
                <span style={{ fontSize: '11px', fontWeight: 800, color: SEV_COLOR[risk.severity] }}>
                    {SEV_ABBR[risk.severity]}
                </span>
            </div>

            {/* Main content */}
            <div style={{ flex: 1, minWidth: 0 }}>
                {/* Risk quote */}
                <div style={{
                    fontFamily: 'var(--fm)',
                    fontSize: '12px',
                    fontWeight: 600,
                    color: 'var(--t1)',
                    marginBottom: '4px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}>
                    "{risk.phrase}"
                </div>

                {/* Impact */}
                <div style={{ fontSize: '12px', color: 'var(--t2)', lineHeight: 1.5, marginBottom: '6px' }}>
                    {risk.impact}
                </div>

                {/* Metadata */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: 'var(--t3)', flexWrap: 'wrap' }}>
                    <span style={{ color: risk.vendor_color ?? 'var(--ac)', fontWeight: 700 }}>
                        {risk.vendor_name}
                    </span>
                    <span>·</span>
                    <span>{categoryLabel}</span>
                    {page > 0 && (
                        <>
                            <span>·</span>
                            <span style={{ fontFamily: 'var(--fm)' }}>p.{page}</span>
                        </>
                    )}
                    {risk.rfp_clause_ref && (
                        <>
                            <span>·</span>
                            <span style={{ fontFamily: 'var(--fm)', color: 'var(--ac)' }}>
                                RFP {risk.rfp_clause_ref}
                            </span>
                        </>
                    )}
                </div>
            </div>

            {/* Right: severity chip + trace button */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                <span style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    color: SEV_COLOR[risk.severity],
                }}>
                    {risk.severity}
                </span>
                <button
                    className="btn btn-g btn-sm"
                    style={{ whiteSpace: 'nowrap' }}
                    onClick={() => {
                      if (onDeepDive) {
                        // Pass the clause ref as the reqId — the Deep Dive tab
                        // should handle looking up by ID or ref.
                        onDeepDive(risk.rfp_clause_ref);
                      } else {
                        onOpen();
                      }
                    }}
                >
                    Trace →
                </button>
            </div>
        </div>
    );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function RiskHeatmap({ heatmap = [], risks = [], onDeepDive }: RiskHeatmapProps) {
    const [drawerRisk, setDrawerRisk] = useState<RiskFinding | null>(null);
    const [drawerOpen, setDrawerOpen] = useState(false);

    const openDrawer = (risk: RiskFinding) => { setDrawerRisk(risk); setDrawerOpen(true); };
    const closeDrawer = () => setDrawerOpen(false);

    // ── Helper: resolve page number from either field ──────────────────────────
    const getPage = (r: RiskFinding) => r.page ?? r.page_number ?? 0;

    // ── Max page: drives the timeline x-axis scale ────────────────────────────
    // Computed dynamically so dots are always distributed proportionally.
    // If every risk has page=0 (backend didn't populate it), fall back to 100
    // so the axis still renders but we don't show any dots.
    const maxPage = useMemo(() => {
        const pages = risks.map(getPage).filter(p => p > 0);
        return pages.length === 0 ? 100 : Math.max(...pages);
    }, [risks]);

    // ── Sort risks by severity for the findings list ───────────────────────────
    const sortedRisks = useMemo(
        () => [...risks].sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]),
        [risks]
    );

    // ── Count risks for a vendor × column cell ────────────────────────────────
    const countForCell = (vendorName: string, colKey: string) =>
        risks.filter(r =>
            r.vendor_name === vendorName &&
            COL_TYPES[colKey]?.includes((r.risk_type ?? '').toLowerCase())
        ).length;

    // ── Find the representative risk to show in the drawer on cell click ──────
    const findRiskForCell = (vendorName: string, severity: RiskSeverity, colKey: string) =>
        risks.find(r =>
            r.vendor_name === vendorName &&
            r.severity === severity &&
            COL_TYPES[colKey]?.includes((r.risk_type ?? '').toLowerCase())
        ) ?? risks.find(r => r.vendor_name === vendorName && r.severity === severity) ?? null;

    // ── Render a heatmap grid cell ────────────────────────────────────────────
    const renderCell = (severity: RiskSeverity | null, vendorName: string, colKey: string) => {
        const count = countForCell(vendorName, colKey);
        const displayCount = severity ? Math.max(count, 1) : 0;

        return (
            <HeatCell
                severity={severity}
                count={displayCount}
                onClick={() => {
                    if (!severity) return;
                    const risk = findRiskForCell(vendorName, severity, colKey);
                    if (risk) openDrawer(risk);
                }}
            />
        );
    };

    // ── Summary badge ─────────────────────────────────────────────────────────
    const critHighCount = risks.filter(r => r.severity === 'Critical' || r.severity === 'High').length;

    return (
        <>
            {/* ── Card 1: Heatmap grid + timeline ─────────────────────────── */}
            <div className="card">
                {/* Header */}
                <div className="ch">
                    <div className="ct">Risk Heatmap — Vendor × Clause Area</div>
                    <div style={{ display: 'flex', gap: '12px' }}>
                        {(['Critical', 'High', 'Medium', 'Low'] as RiskSeverity[]).map(s => (
                            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: 'var(--t2)' }}>
                                <div style={{ width: '10px', height: '10px', borderRadius: '2px', background: SEV_BG[s] }} />
                                {s}
                            </div>
                        ))}
                    </div>
                </div>

                {/* Grid */}
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '700px' }}>
                        <thead>
                            <tr>
                                <th style={{ ...TH, textAlign: 'left', padding: '10px 18px', borderRight: '2px solid rgba(15,17,23,.1)', minWidth: '200px', color: 'var(--t3)' }}>
                                    Vendor
                                </th>
                                <th style={TH}>Liability Cap</th>
                                <th style={TH}>Price / Scope</th>
                                <th style={TH}>Obligations</th>
                                <th style={TH}>IP / Data</th>
                                <th style={{ ...TH, borderRight: 'none' }}>Exit Term</th>
                            </tr>
                        </thead>
                        <tbody>
                            {heatmap.map((cell, i) => (
                                <tr key={i}>
                                    <td style={{
                                        padding: '12px 18px',
                                        fontSize: '13px',
                                        fontWeight: 600,
                                        color: 'var(--t1)',
                                        borderRight: '2px solid rgba(15,17,23,.1)',
                                        borderBottom: '1px solid var(--border)',
                                    }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: cell.vendor_color, flexShrink: 0 }} />
                                            {cell.vendor_name}
                                        </div>
                                    </td>
                                    {renderCell(cell.liability_cap, cell.vendor_name, 'liability_cap')}
                                    {renderCell(cell.price_scope, cell.vendor_name, 'price_scope')}
                                    {renderCell(cell.obligation, cell.vendor_name, 'obligation')}
                                    {renderCell(cell.ip_data, cell.vendor_name, 'ip_data')}
                                    {renderCell(cell.exit, cell.vendor_name, 'exit')}
                                </tr>
                            ))}

                            {heatmap.length === 0 && (
                                <tr>
                                    <td colSpan={6} style={{ padding: '32px', textAlign: 'center', color: 'var(--t3)', fontSize: '13px' }}>
                                        No risk data available. Run an audit to populate the heatmap.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>

                {/* ── Document Risk Timeline ─────────────────────────────── */}
                <div style={{ padding: '20px 20px 24px', borderTop: '1px solid var(--border)' }}>
                    <div className="sec-lbl" style={{ marginBottom: '2px' }}>Document Risk Timeline</div>
                    <div style={{ fontSize: '11px', color: 'var(--t3)', marginBottom: '20px' }}>
                        Position of risk flags across proposal pages — clusters signal buried terms
                    </div>

                    {heatmap.map(cell => {
                        // Only show risks that have a valid page number
                        const vendorRisks = risks.filter(r =>
                            r.vendor_name === cell.vendor_name && getPage(r) > 0
                        );

                        return (
                            <div key={`tl-${cell.vendor_name}`} className="rtl-vendor">
                                <div className="rtl-vendor-label">
                                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: cell.vendor_color, flexShrink: 0 }} />
                                    <span>{cell.vendor_name}</span>
                                    {vendorRisks.length === 0 && (
                                        <span style={{ fontSize: '11px', color: 'var(--t3)', fontWeight: 400 }}>
                                            — No risks detected
                                        </span>
                                    )}
                                </div>

                                <div className="rtl-track">
                                    <div className="rtl-bar" />
                                    {/* [MOTION] Sweeping line + scanner head */}
                                    <div className="rtl-fill" />
                                    <div className="rtl-scanner" />

                                    {vendorRisks.map(r => {
                                        const pg = getPage(r);
                                        // Map page → percentage of track width.
                                        // Clamp to [1%, 97%] so dots never overflow the edges.
                                        const pct = Math.min(97, Math.max(1, (pg / maxPage) * 100));
                                        // [MOTION] Sync pin pop with scanner position over a 2s sweep
                                        const delaySeconds = (pct / 100) * 2 + 0.05;

                                        return (
                                            <div
                                                key={r.id}
                                                className="rtl-flag rtl-flag-anim"
                                                style={{ left: `${pct}%`, animationDelay: `${delaySeconds}s` }}
                                                title={`${r.severity}: "${r.phrase}" · p.${pg}`}
                                                onClick={() => openDrawer(r)}
                                            >
                                                <div
                                                    className="rtl-pin"
                                                    style={{ background: SEV_COLOR[r.severity] }}
                                                />
                                                <div className="rtl-pg">p.{pg}</div>
                                            </div>
                                        );
                                    })}

                                    {/* Cluster annotation: show if 2+ dots within 15% of each other */}
                                    {(() => {
                                        if (vendorRisks.length < 2) return null;
                                        const pcts = vendorRisks.map(r =>
                                            Math.min(97, Math.max(1, (getPage(r) / maxPage) * 100))
                                        );
                                        const span = Math.max(...pcts) - Math.min(...pcts);
                                        if (span > 15) return null;
                                        const mid = pcts.reduce((a, b) => a + b, 0) / pcts.length;
                                        return (
                                            <div style={{
                                                position: 'absolute',
                                                left: `${mid}%`,
                                                transform: 'translateX(-50%)',
                                                top: '-20px',
                                                fontSize: '9px',
                                                fontWeight: 700,
                                                color: 'var(--part)',
                                                whiteSpace: 'nowrap',
                                                background: 'var(--part-bg)',
                                                padding: '1px 5px',
                                                borderRadius: '3px',
                                                pointerEvents: 'none',
                                            }}>
                                                ⚑ Cluster
                                            </div>
                                        );
                                    })()}
                                </div>
                            </div>
                        );
                    })}

                    {/* Page axis ruler */}
                    {heatmap.length > 0 && (
                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: '9px',
                            color: 'var(--t3)',
                            fontFamily: 'var(--fm)',
                            marginTop: '6px',
                        }}>
                            <span>p.1</span>
                            <span>p.{Math.round(maxPage / 2)}</span>
                            <span>p.{maxPage}</span>
                        </div>
                    )}
                </div>
            </div>

            {/* ── Card 2: All Risk Findings ────────────────────────────────── */}
            <div className="card">
                <div className="ch">
                    <div className="ct">All Risk Findings</div>
                    {critHighCount > 0 && (
                        <span className="bd bd-crit">
                            {critHighCount} Critical / High
                        </span>
                    )}
                </div>

                <div style={{ padding: 0 }}>
                    {sortedRisks.length === 0 ? (
                        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--t3)', fontSize: '13px' }}>
                            No risk findings detected across all vendor proposals.
                        </div>
                    ) : (
                        // [MOTION] scroll shadow wrapper
                        <div style={{ position: 'relative', overflow: 'hidden' }}>
                            <div
                                // [MOTION] scroll shadow — appears only when scrolled
                                style={{
                                    position: 'absolute', bottom: 0, left: 0, right: 0, height: 40,
                                    background: 'linear-gradient(to top, var(--surface) 0%, transparent 100%)',
                                    pointerEvents: 'none',
                                    zIndex: 2,
                                }}
                            />
                            <div style={{ maxHeight: 520, overflowY: 'auto' }}>
                                {sortedRisks.map((risk, i) => (
                                    <RiskCard
                                        key={risk.id || i}
                                        risk={risk}
                                        isLast={i === sortedRisks.length - 1}
                                        onOpen={() => openDrawer(risk)}
                                        onDeepDive={onDeepDive}
                                    />
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* ── Slide-in drawer ───────────────────────────────────────────── */}
            <RiskDrawer
                risk={drawerRisk}
                open={drawerOpen}
                onClose={closeDrawer}
            />
        </>
    );
}