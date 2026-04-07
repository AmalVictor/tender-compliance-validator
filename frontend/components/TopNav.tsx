'use client';

// components/TopNav.tsx
import React from 'react';
import type { TabId } from './Sidebar';
import type { AuditSummary } from '@/types';
import styles from './TopNav.module.css';

interface TopNavProps {
    projectName: string;
    projectSub: string;
    summary: AuditSummary | null;
    onTabChange: (tab: TabId) => void;
    onExport: () => void;
}

const REPORT_STEPS = [
    'Compiling compliance matrix',
    'Analyzing risk findings',
    'Building methodology note',
    'Finalizing PDF export',
];

// [MOTION] CountUp — animates a number from 0 to target on mount
function CountUp({ target, suffix = '' }: { target: number; suffix?: string }) {
    const [display, setDisplay] = React.useState(0);
    React.useEffect(() => {
        if (!target) return;
        const duration = 1400;
        const steps = 30;
        const step = target / steps;
        let current = 0;
        const interval = setInterval(() => {
            current += step;
            if (current >= target) {
                setDisplay(target);
                clearInterval(interval);
            } else {
                setDisplay(Math.round(current));
            }
        }, duration / steps);
        return () => clearInterval(interval);
    }, [target]);
    return <span style={{ animation: 'countUp .3s ease forwards' }}>{display}{suffix}</span>;
}

function ReportGenerationModal({ onComplete }: { onComplete: () => void }) {
    const [stepIndex, setStepIndex] = React.useState(0);
    const [done, setDone] = React.useState(false);

    React.useEffect(() => {
        const timers: ReturnType<typeof setTimeout>[] = [];
        REPORT_STEPS.forEach((_, i) => {
            timers.push(setTimeout(() => setStepIndex(i), i * 900));
        });
        timers.push(setTimeout(() => {
            setDone(true);
            setTimeout(onComplete, 600);
        }, REPORT_STEPS.length * 900));
        return () => timers.forEach(clearTimeout);
    }, [onComplete]);

    return (
        <div style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            background: 'rgba(0,0,0,.4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            animation: 'overlayIn .2s ease forwards',
        }}>
            <div style={{
                background: 'var(--surface)', borderRadius: 16,
                padding: '32px 36px', width: 380, boxShadow: 'var(--sh3)',
                animation: 'popIn .28s cubic-bezier(0.34,1.4,0.64,1) forwards',
            }}>
                <div style={{
                    width: 56, height: 56, borderRadius: 14,
                    background: done ? 'var(--full-bg)' : 'var(--ac-bg)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    margin: '0 auto 20px',
                    transition: 'background .4s ease',
                    boxShadow: done ? '0 0 0 0 transparent' : '0 4px 18px rgba(12,123,114,.2)',
                    animation: done ? 'none' : 'glowPulse 1.6s ease infinite',
                }}>
                    {done ? (
                        <span style={{ fontSize: 28, animation: 'checkBounce .4s cubic-bezier(0.34,1.4,0.64,1) forwards' }}>✓</span>
                    ) : (
                        <svg width="26" height="26" fill="none" viewBox="0 0 24 24" stroke="var(--ac)" strokeWidth={1.8}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                        </svg>
                    )}
                </div>
                <div style={{ textAlign: 'center', marginBottom: 24 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>
                        {done ? 'Report Ready' : 'Generating Report...'}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--t3)' }}>
                        {done ? 'Your download will start automatically' : 'This takes a few seconds'}
                    </div>
                </div>
                <div style={{ height: 4, background: 'var(--bg2)', borderRadius: 2, overflow: 'hidden', marginBottom: 20 }}>
                    <div style={{
                        height: '100%',
                        width: done ? '100%' : `${((stepIndex + 1) / REPORT_STEPS.length) * 100}%`,
                        background: done ? 'var(--full)' : 'var(--ac)',
                        borderRadius: 2,
                        transition: 'width .6s var(--ease-out), background .4s ease',
                    }} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {REPORT_STEPS.map((step, i) => {
                        const isComplete = i < stepIndex || done;
                        const isActive = i === stepIndex && !done;
                        return (
                            <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 10, animation: 'fadeUp .18s ease both', animationDelay: `${i * 0.06}s` }}>
                                <div style={{
                                    width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    background: isComplete ? 'var(--full-bg)' : isActive ? 'var(--ac-bg)' : 'var(--bg2)',
                                    border: `1.5px solid ${isComplete ? 'var(--full)' : isActive ? 'var(--ac)' : 'var(--border)'}`,
                                    transition: 'all .3s ease',
                                }}>
                                    {isComplete && <span style={{ fontSize: 11, color: 'var(--full)', animation: 'stepTick .3s forwards' }}>✓</span>}
                                    {isActive && <div style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ac)', animation: 'pulseDot 1s ease infinite' }} />}
                                </div>
                                <span style={{ fontSize: 13, color: isComplete ? 'var(--t2)' : isActive ? 'var(--t1)' : 'var(--t3)', fontWeight: isActive ? 600 : 400 }}>
                                    {step}
                                </span>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}

export function TopNav({ projectName, projectSub, summary, onTabChange, onExport }: TopNavProps) {
    const [showReportModal, setShowReportModal] = React.useState(false);
    return (
        <div className={styles.topbar}>
            <div className={styles.pj}>
                <div className={styles.pjName}>{projectName}</div>
                <div className={styles.pjSub}>{projectSub}</div>
            </div>

            {summary && (
                <div className={styles.kpiBand}>
                    <div className={styles.kpi}>
                        <div className={`${styles.kv} ${styles.g}`}><CountUp target={summary.best_compliance_score} suffix="%" /></div>
                        <div className={styles.kl}>Best Score</div>
                    </div>
                    <div className={styles.kpi}>
                        <div className={`${styles.kv} ${styles.r}`}><CountUp target={summary.critical_risks} /></div>
                        <div className={styles.kl}>Crit. Risks</div>
                    </div>
                    <div className={styles.kpi}>
                        <div className={`${styles.kv} ${styles.a}`}><CountUp target={summary.gap_count} /></div>
                        <div className={styles.kl}>Gaps</div>
                    </div>
                    <div className={styles.kpi}>
                        <div className={`${styles.kv} ${styles.b}`}><CountUp target={summary.vendor_count} /></div>
                        <div className={styles.kl}>Vendors</div>
                    </div>
                </div>
            )}

            <div className={styles.actions}>
                <button
                    className="btn btn-g"
                    onClick={() => onTabChange('deepdive')}
                >
                    <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 15.803 7.5 7.5 0 0015.803 15.803z" />
                    </svg>
                    Deep Dive
                </button>
                <button className="btn btn-p" onClick={() => setShowReportModal(true)}>
                    <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                    </svg>
                    Export PDF
                </button>
            </div>
            {showReportModal && (
                <ReportGenerationModal
                    onComplete={() => {
                        onExport();
                        setShowReportModal(false);
                    }}
                />
            )}
        </div>
    );
}