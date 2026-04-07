// components/StatusBadge.tsx
// Reusable compliance status badge — maps FULL/PARTIAL/NONE/AMBIGUOUS
// to the exact chip/badge classes from the mockup.

import type { ComplianceStatus, RiskSeverity } from '../types';

type BadgeVariant = ComplianceStatus | RiskSeverity | 'Mandatory' | 'Recommended' | string;

interface StatusBadgeProps {
    status: BadgeVariant;
    size?: 'chip' | 'badge';
    className?: string;
}

const CHIP_CLASS: Record<string, string> = {
    FULL: 'chip chip-full',
    PARTIAL: 'chip chip-part',
    NONE: 'chip chip-none',
    AMBIGUOUS: 'chip chip-ambg',
};

const BADGE_CLASS: Record<string, string> = {
    FULL: 'bd bd-full',
    PARTIAL: 'bd bd-part',
    NONE: 'bd bd-none',
    AMBIGUOUS: 'bd bd-ambg',
    Critical: 'bd bd-crit',
    High: 'bd bd-high',
    Medium: 'bd bd-med',
    Low: 'bd bd-low',
    Mandatory: 'bd bd-mand',
    Recommended: 'bd bd-rec',
    Technical: 'bd bd-tech',
    Legal: 'bd bd-leg',
    Financial: 'bd bd-fin',
    Administrative: 'bd bd-adm',
};

const DISPLAY_LABELS: Record<string, string> = {
    FULL: 'Full',
    PARTIAL: 'Partial',
    NONE: 'None',
    AMBIGUOUS: 'Ambig',
};

export function StatusBadge({ status, size = 'chip', className = '' }: StatusBadgeProps) {
    const map = size === 'chip' ? CHIP_CLASS : BADGE_CLASS;
    const cls = map[status] ?? (size === 'chip' ? 'chip' : 'bd');
    const label = DISPLAY_LABELS[status] ?? status;

    return (
        <span className={`${cls} ${className}`.trim()}>
            {label}
        </span>
    );
}

// ── Confidence visual ─────────────────────────
interface ConfidenceBarProps {
    value: number; // 0–1
    centered?: boolean;
}

export function ConfidenceBar({ value, centered = false }: ConfidenceBarProps) {
    const pct = Math.round(value * 100);
    const color = value >= 0.8 ? 'var(--full)' : value >= 0.6 ? 'var(--part)' : 'var(--none)';

    return (
        <div
            className="conf-row"
            style={centered ? { justifyContent: 'center' } : undefined}
        >
            <div
                style={{
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: color,
                    flexShrink: 0,
                }}
            />
            <div className="conf-bar">
                <div
                    className="conf-fill"
                    style={{ width: `${pct}%`, background: color }}
                />
            </div>
            <span className="mono text-xs" style={{ color }}>
                {pct}%
            </span>
        </div>
    );
}