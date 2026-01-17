'use client';

import { useState, useEffect } from 'react';
import styles from './page.module.css';

interface ApiStatus {
  health: 'checking' | 'healthy' | 'unhealthy';
  version: string | null;
  message: string | null;
}

export default function Home() {
  const [name, setName] = useState('');
  const [greeting, setGreeting] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState<ApiStatus>({
    health: 'checking',
    version: null,
    message: null,
  });

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  // Check API health on mount
  useEffect(() => {
    async function checkApi() {
      try {
        // Check health
        const healthRes = await fetch(`${apiUrl}/health`);
        if (!healthRes.ok) throw new Error('Health check failed');

        // Get version
        const versionRes = await fetch(`${apiUrl}/api/version`);
        const versionData = await versionRes.json();

        // Get hello message
        const helloRes = await fetch(`${apiUrl}/api/hello`);
        const helloData = await helloRes.json();

        setApiStatus({
          health: 'healthy',
          version: versionData.version,
          message: helloData.message,
        });
      } catch (error) {
        setApiStatus({
          health: 'unhealthy',
          version: null,
          message: 'Could not connect to backend API',
        });
      }
    }
    checkApi();
  }, [apiUrl]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/hello`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      setGreeting(data.message);
    } catch (error) {
      setGreeting('Error connecting to API');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className={styles.main}>
      <div className={styles.container}>
        <header className={styles.header}>
          <h1 className={styles.title}>Software Factory</h1>
          <p className={styles.subtitle}>Autonomous development powered by Claude</p>
        </header>

        <section className={styles.status}>
          <h2>API Status</h2>
          <div className={styles.statusGrid}>
            <div className={styles.statusItem}>
              <span className={styles.statusLabel}>Backend</span>
              <span
                className={`${styles.statusBadge} ${
                  apiStatus.health === 'healthy'
                    ? styles.healthy
                    : apiStatus.health === 'unhealthy'
                      ? styles.unhealthy
                      : styles.checking
                }`}
              >
                {apiStatus.health === 'checking'
                  ? 'Checking...'
                  : apiStatus.health === 'healthy'
                    ? 'Connected'
                    : 'Disconnected'}
              </span>
            </div>
            {apiStatus.version && (
              <div className={styles.statusItem}>
                <span className={styles.statusLabel}>Version</span>
                <span className={styles.statusValue}>{apiStatus.version}</span>
              </div>
            )}
          </div>
          {apiStatus.message && (
            <p className={styles.apiMessage}>
              {apiStatus.health === 'healthy' ? 'Backend says: ' : ''}
              {apiStatus.message}
            </p>
          )}
        </section>

        <section className={styles.demo}>
          <h2>Try the API</h2>
          <form onSubmit={handleSubmit} className={styles.form}>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Enter your name"
              className={styles.input}
              disabled={apiStatus.health !== 'healthy'}
            />
            <button
              type="submit"
              className={styles.button}
              disabled={loading || apiStatus.health !== 'healthy'}
            >
              {loading ? 'Sending...' : 'Say Hello'}
            </button>
          </form>
          {greeting && <p className={styles.greeting}>{greeting}</p>}
        </section>

        <section className={styles.info}>
          <h2>Getting Started</h2>
          <div className={styles.cards}>
            <a
              href="https://github.com/anthropics/claude-code"
              target="_blank"
              rel="noopener noreferrer"
              className={styles.card}
            >
              <h3>Claude Code</h3>
              <p>Learn about the AI coding assistant powering this factory</p>
            </a>
            <a href="/docs" className={styles.card}>
              <h3>API Docs</h3>
              <p>Explore the backend API documentation</p>
            </a>
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className={styles.card}
            >
              <h3>View Source</h3>
              <p>Check out the repository and contribute</p>
            </a>
          </div>
        </section>

        <footer className={styles.footer}>
          <p>
            Built with <a href="https://nextjs.org">Next.js</a> +{' '}
            <a href="https://fastapi.tiangolo.com">FastAPI</a> +{' '}
            <a href="https://anthropic.com">Claude</a>
          </p>
        </footer>
      </div>
    </main>
  );
}
