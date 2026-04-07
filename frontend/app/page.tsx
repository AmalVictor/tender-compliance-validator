'use client';
// src/app/page.tsx — Login Screen

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from '@/login.module.css';

export default function LoginPage() {
  const router = useRouter();
  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password.trim()) {
      setError('Please enter your email and password.');
      return;
    }
    setError('');
    setLoading(true);
    // In production: POST /api/auth/login and store JWT
    // For demo: any credentials accepted
    await new Promise((r) => setTimeout(r, 850));
    setLoading(false);
    router.push('/projects');
  }

  function loadDemo() {
    setEmail('demo@tenderai.co.za');
    setPassword('demo1234');
    setError('');
  }

  return (
    <div className={styles.root}>
      {/* Left panel */}
      <div className={styles.left}>
        <div className={styles.brand}>
          <div className={styles.logoMark}>TA</div>
          <span className={styles.brandName}>TenderAI</span>
        </div>
        <h1 className={styles.headline}>
          AI-powered compliance<br />for public procurement
        </h1>
        <p className={styles.sub}>
          Validate vendor proposals against RFP requirements in minutes, not weeks.
          Trusted by procurement officers, legal teams, and supply chain specialists.
        </p>
        <div className={styles.stats}>
          <div className={styles.stat}>
            <div className={styles.statVal}>40%</div>
            <div className={styles.statLbl}>of public tenders rejected for admin errors — caught automatically before submission</div>
          </div>
          <div className={styles.stat}>
            <div className={styles.statVal}>4.2s</div>
            <div className={styles.statLbl}>median audit run time for 10 requirements × 3 vendors</div>
          </div>
          <div className={styles.stat}>
            <div className={styles.statVal}>92%</div>
            <div className={styles.statLbl}>AI confidence via cross-encoder reranking + NLI entailment classification</div>
          </div>
        </div>
      </div>

      {/* Right panel */}
      <div className={styles.right}>
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <h2 className={styles.cardTitle}>Sign in to TenderAI</h2>
            <p className={styles.cardSub}>Demo — any credentials accepted</p>
          </div>

          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="email">Email address</label>
              <input
                id="email"
                type="email"
                className={styles.input}
                placeholder="you@department.gov.za"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoFocus
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                className={styles.input}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>

            {error && <div className={styles.errorMsg}>{error}</div>}

            <button type="submit" className={styles.submitBtn} disabled={loading}>
              {loading ? (
                <><span className="spin" style={{ fontSize: 13 }}>⟳</span> Signing in…</>
              ) : (
                'Continue →'
              )}
            </button>
          </form>

          <div className={styles.divider}><span>or</span></div>

          <button className={styles.demoBtn} onClick={loadDemo}>
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z" />
            </svg>
            Load demo credentials
          </button>

          <p className={styles.footer}>
            Don&apos;t have an account?{' '}
            <a href="#" className={styles.link}>Request access</a>
          </p>
        </div>
      </div>
    </div>
  );
}