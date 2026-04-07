'use client';

import React, { useState } from 'react';
import type { MatrixRow, RequirementCategory } from '../types';
import { StatusBadge, ConfidenceBar } from './StatusBadge';

interface ComplianceMatrixProps {
    matrix: MatrixRow[];
    onDeepDive: (reqId: string) => void;
}

type FilterType = 'All' | 'NONE' | 'PARTIAL' | 'Mandatory';

export function ComplianceMatrix({ matrix, onDeepDive }: ComplianceMatrixProps) {
    const [filter, setFilter] = useState<FilterType>('All');
    const [isFilterTransitioning, setIsFilterTransitioning] = React.useState(false);
    // [MOTION] cell pulse ref — triggers CSS animation on the clicked cell
    const [pulsingCell, setPulsingCell] = React.useState<string | null>(null);
    // [MOTION] filter key — changing it remounts filtered rows so stagger replays
    const [filterKey, setFilterKey] = React.useState(0);

    // Filter matrix
    const safeMatrix = matrix || [];
    const filteredMatrix = safeMatrix.filter((row) => {
        if (filter === 'All') return true;
        if (filter === 'Mandatory') return row.requirement.criticality === 'Mandatory';
        if (filter === 'NONE') return row.matches.some((m) => m.status === 'NONE');
        if (filter === 'PARTIAL') return row.matches.some((m) => m.status === 'PARTIAL');
        return true;
    });

    // Group by category
    const grouped = filteredMatrix.reduce((acc, row) => {
        const cat = row.requirement.category;
        if (!acc[cat]) acc[cat] = [];
        acc[cat].push(row);
        return acc;
    }, {} as Record<RequirementCategory, MatrixRow[]>);

    // Get evaluated vendor columns in a stable order.
    const vendorNames: string[] = [];
    safeMatrix.forEach((row) => {
        row.matches.forEach((m) => {
            if (!vendorNames.includes(m.vendor_name)) vendorNames.push(m.vendor_name);
        });
    });

    const triggerFilterChange = React.useCallback((next: FilterType) => {
        if (next === filter) return;
        setIsFilterTransitioning(true);
        // [MOTION] fade out old rows first, then swap filter and fade in staggered rows
        setTimeout(() => {
            setFilter(next);
            setFilterKey((k) => k + 1);
            setIsFilterTransitioning(false);
        }, 200);
    }, [filter]);

    return (
        <div className="card">
            <div className="ch">
                <div className="ct">Compliance Matrix</div>
                <div className="row">
                    <button className={`fb ${filter === 'All' ? 'on' : ''}`} onClick={() => triggerFilterChange('All')}>All Requirements</button>
                    <button className={`fb ${filter === 'NONE' ? 'on' : ''}`} onClick={() => triggerFilterChange('NONE')}>Gaps only</button>
                    <button className={`fb ${filter === 'PARTIAL' ? 'on' : ''}`} onClick={() => triggerFilterChange('PARTIAL')}>Partial only</button>
                    <button className={`fb ${filter === 'Mandatory' ? 'on' : ''}`} onClick={() => triggerFilterChange('Mandatory')}>Mandatory</button>
                </div>
            </div>

            <div className="cb" style={{ padding: 0 }}>
                <div className="mx-wrap" style={{ overflow: 'auto', maxHeight: '700px' }}>
                    <table id="mx-table" style={{ width: '100%', borderCollapse: 'collapse', minWidth: '800px', fontSize: '13px' }}>
                        <thead style={{ position: 'sticky', top: 0, zIndex: 10, background: '#FAFAF8' }}>
                            <tr>
                                <th
                                    className="req-col"
                                    style={{
                                        textAlign: 'left',
                                        padding: '12px 18px',
                                        borderBottom: '2px solid rgba(15,17,23,.1)',
                                        borderRight: '1px solid rgba(15,17,23,.06)',
                                        position: 'sticky',
                                        left: 0,
                                        zIndex: 11,
                                        background: '#FAFAF8',
                                        minWidth: '280px',
                                        fontSize: '10px',
                                        textTransform: 'uppercase',
                                        letterSpacing: '.07em',
                                        color: 'var(--t3)'
                                    }}
                                >
                                    Requirement & Clause
                                </th>
                                {vendorNames.map((vName, idx) => (
                                    <th
                                        key={idx}
                                        className="v-col"
                                        style={{
                                            textAlign: 'center',
                                            padding: '12px 0',
                                            borderBottom: '2px solid rgba(15,17,23,.1)',
                                            borderRight: '1px solid rgba(15,17,23,.06)',
                                            minWidth: '180px',
                                            fontSize: '10px',
                                            textTransform: 'uppercase',
                                            letterSpacing: '.07em',
                                            color: 'var(--t3)'
                                        }}
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                                            {/* You might want to use actual vendor colors from context/props if needed */}
                                            {vName}
                                        </div>
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody key={filterKey} style={{ opacity: isFilterTransitioning ? 0 : 1, transition: 'opacity .2s ease' }}>
                            {Object.entries(grouped).map(([category, rows]) => (
                                <React.Fragment key={category}>
                                    <tr>
                                        <td
                                            colSpan={vendorNames.length + 1}
                                            style={{
                                                padding: '10px 18px',
                                                background: 'var(--bg)',
                                                fontWeight: 700,
                                                fontSize: '11px',
                                                textTransform: 'uppercase',
                                                letterSpacing: '.08em',
                                                color: 'var(--t3)'
                                            }}
                                        >
                                            {category} Requirements
                                        </td>
                                    </tr>
                                    {rows.map((row, rowIndex) => (
                                        <tr key={row.requirement.id} className="mx-row mx-row-enter" style={{ borderBottom: '1px solid var(--border)', animationDelay: `${rowIndex * 0.04}s` }}>
                                            <td
                                                style={{
                                                    padding: '14px 18px',
                                                    borderRight: '1px solid var(--border)',
                                                    position: 'sticky',
                                                    left: 0,
                                                    background: '#fff',
                                                    verticalAlign: 'top',
                                                    zIndex: 1
                                                }}
                                            >
                                                <div style={{ fontWeight: 600, color: 'var(--t1)', marginBottom: '6px', lineHeight: 1.4 }}>
                                                    {row.requirement.normalised || row.requirement.raw_text}
                                                </div>
                                                <div className="row mt2">
                                                    <StatusBadge status={row.requirement.criticality} size="badge" />
                                                    <span className="mono text-xs muted">{row.requirement.ref}</span>
                                                </div>
                                            </td>
                                            {vendorNames.map((vName, idx) => {
                                                const match = row.matches.find((m) => m.vendor_name === vName);
                                                // The UX expects FULL/PARTIAL/NONE chips for missing/other statuses.
                                                const normalizedStatus = match?.status === 'FULL' || match?.status === 'PARTIAL' || match?.status === 'NONE'
                                                    ? match.status
                                                    : 'NONE';
                                                const confidence = match?.confidence ?? 0;
                                                const evidenceText = match?.evidence ?? '';
                                                return (
                                                    <td
                                                        key={`${row.requirement.id}-${vName}-${idx}`}
                                                        className={`vc-td mx-cell-hover ${pulsingCell === `${row.requirement.id}-${vName}` ? 'cell-pulse' : ''}`}
                                                        style={{
                                                            padding: '14px',
                                                            borderRight: '1px solid var(--border)',
                                                            verticalAlign: 'top',
                                                            cursor: 'pointer',
                                                            background: normalizedStatus === 'NONE' ? 'var(--none-bg)' : 'transparent',
                                                            transition: 'background .15s'
                                                        }}
                                                        onClick={() => {
                                                            const cellKey = `${row.requirement.id}-${vName}`;
                                                            setPulsingCell(cellKey);
                                                            // [MOTION] 150ms intentional delay before navigation — feels deliberate
                                                            setTimeout(() => {
                                                                setPulsingCell(null);
                                                                onDeepDive(row.requirement.id);
                                                            }, 150);
                                                        }}
                                                    >
                                                        <StatusBadge status={normalizedStatus} size="chip" />
                                                        <div style={{ marginTop: '10px' }}>
                                                            <div style={{
                                                                fontSize: '9px',
                                                                color: 'var(--t3)',
                                                                fontWeight: 700,
                                                                letterSpacing: '0.06em',
                                                                marginBottom: '4px'
                                                            }}>
                                                                AI CONFIDENCE
                                                            </div>
                                                            <ConfidenceBar value={confidence} />
                                                        </div>
                                                        {!!evidenceText && (
                                                            <div style={{ fontSize: '11px', color: 'var(--t2)', marginTop: '8px', fontStyle: 'italic', lineHeight: 1.4, opacity: 0.85 }}>
                                                                "{evidenceText.substring(0, 80)}{evidenceText.length > 80 ? '...' : ''}"
                                                            </div>
                                                        )}
                                                        {match?.section_ref && (
                                                            <div style={{ fontSize: '10px', color: 'var(--t3)', fontFamily: 'var(--font-mono), monospace', marginTop: '4px' }}>
                                                                {match.section_ref}
                                                            </div>
                                                        )}
                                                    </td>
                                                );
                                            })}
                                        </tr>
                                    ))}
                                </React.Fragment>
                            ))}
                            {filteredMatrix.length === 0 && (
                                <tr>
                                    <td colSpan={vendorNames.length + 1} style={{ padding: '30px', textAlign: 'center', color: 'var(--t3)' }}>
                                        No requirements found for the selected filter.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
