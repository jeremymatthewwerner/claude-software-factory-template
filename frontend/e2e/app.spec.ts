import { test, expect, Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Shared fixtures
// ---------------------------------------------------------------------------

/**
 * Intercept all three backend API calls and return healthy responses.
 * Uses route interception so tests run without a real backend — no server
 * startup time, no network latency, no flakiness from external state.
 *
 * Performance note: page.route() is registered synchronously; the interception
 * happens at the network layer, not via arbitrary timeouts.
 */
async function mockHealthyBackend(page: Page) {
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'healthy' } }));
  await page.route('**/api/version', (route) => route.fulfill({ json: { version: '1.0.0' } }));
  await page.route('**/api/hello', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: { message: 'Hello, World!' } });
    }
    return route.continue();
  });
}

async function mockUnhealthyBackend(page: Page) {
  await page.route('**/health', (route) => route.abort('failed'));
  await page.route('**/api/version', (route) => route.abort('failed'));
  await page.route('**/api/hello', (route) => route.abort('failed'));
}

// ---------------------------------------------------------------------------
// Page load & initial state
// ---------------------------------------------------------------------------

test.describe('page load', () => {
  test('renders title and subtitle', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    // Playwright auto-waits for the element — no waitForTimeout needed
    await expect(page.getByRole('heading', { name: 'Software Factory' })).toBeVisible();
    await expect(page.getByText('Autonomous development powered by Claude')).toBeVisible();
  });

  test('shows Checking status immediately on load', async ({ page }) => {
    // Intercept health with a never-resolving promise to inspect loading state
    await page.route('**/health', () => {
      // intentionally never fulfils — stalls the API
    });
    await page.route('**/api/version', () => {});
    await page.route('**/api/hello', () => {});

    await page.goto('/');

    // The "Checking..." badge must appear synchronously before any response
    await expect(page.getByText('Checking...')).toBeVisible();
  });

  test('shows Connected after healthy backend response', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    // Wait for the specific DOM state driven by the API response — not time
    await expect(page.getByText('Connected')).toBeVisible();
    await expect(page.getByText('1.0.0')).toBeVisible();
  });

  test('shows Disconnected when backend is unreachable', async ({ page }) => {
    await mockUnhealthyBackend(page);
    await page.goto('/');

    await expect(page.getByText('Disconnected')).toBeVisible();
    await expect(page.getByText('Could not connect to backend API')).toBeVisible();
  });

  test('renders Getting Started cards', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    await expect(page.getByText('Getting Started')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Claude Code' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'API Docs' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'View Source' })).toBeVisible();
  });

  test('renders footer technology links', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    await expect(page.getByRole('link', { name: 'Next.js' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'FastAPI' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Claude', exact: true })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// API status section
// ---------------------------------------------------------------------------

test.describe('api status', () => {
  test('shows version badge after connecting', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    // Waiting for the version label — state is driven by API response, not time
    await expect(page.getByText('Version').first()).toBeVisible();
    await expect(page.getByText('1.0.0')).toBeVisible();
  });

  test('does not show version badge while checking', async ({ page }) => {
    // Stall the version endpoint
    await page.route('**/health', (route) => route.fulfill({ json: { status: 'healthy' } }));
    await page.route('**/api/version', () => {});
    await page.route('**/api/hello', () => {});

    await page.goto('/');

    await expect(page.getByText('Checking...')).toBeVisible();
    await expect(page.getByText('Version')).not.toBeVisible();
  });

  test('shows backend message when healthy', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    await expect(page.getByText('Connected')).toBeVisible();
    await expect(page.getByText(/Backend says:/)).toBeVisible();
    await expect(page.getByText(/Hello, World!/)).toBeVisible();
  });

  test('does not show Backend says prefix when disconnected', async ({ page }) => {
    await mockUnhealthyBackend(page);
    await page.goto('/');

    await expect(page.getByText('Disconnected')).toBeVisible();
    await expect(page.getByText(/Backend says:/)).not.toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Hello form
// ---------------------------------------------------------------------------

test.describe('hello form', () => {
  test('input and button are disabled when disconnected', async ({ page }) => {
    await mockUnhealthyBackend(page);
    await page.goto('/');

    await expect(page.getByText('Disconnected')).toBeVisible();

    const input = page.getByPlaceholder('Enter your name');
    const button = page.getByRole('button', { name: /say hello/i });

    await expect(input).toBeDisabled();
    await expect(button).toBeDisabled();
  });

  test('input and button are enabled when connected', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    await expect(page.getByText('Connected')).toBeVisible();

    await expect(page.getByPlaceholder('Enter your name')).toBeEnabled();
    await expect(page.getByRole('button', { name: /say hello/i })).toBeEnabled();
  });

  test('submitting a name shows personalized greeting', async ({ page }) => {
    await mockHealthyBackend(page);
    // Intercept POST separately so we can return a custom response
    await page.route('**/api/hello', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({ json: { message: 'Hello, Alice!' } });
      }
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('Alice');

    // waitForResponse waits for the network event — no arbitrary timeout
    const [response] = await Promise.all([
      page.waitForResponse('**/api/hello'),
      page.getByRole('button', { name: /say hello/i }).click(),
    ]);

    expect(response.status()).toBe(200);
    await expect(page.getByText('Hello, Alice!')).toBeVisible();
  });

  test('shows Sending... during submission and clears after', async ({ page }) => {
    await mockHealthyBackend(page);

    // Slow POST to observe the loading state
    let resolvePost!: () => void;
    const postPending = new Promise<void>((res) => {
      resolvePost = res;
    });

    await page.route('**/api/hello', async (route) => {
      if (route.request().method() === 'POST') {
        await postPending;
        return route.fulfill({ json: { message: 'Hello, Alice!' } });
      }
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('Alice');
    await page.getByRole('button', { name: /say hello/i }).click();

    // Button switches to "Sending..." immediately — Playwright auto-waits for it
    await expect(page.getByRole('button', { name: /sending/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /sending/i })).toBeDisabled();

    resolvePost();

    // After response, loading state clears — no waitForTimeout
    await expect(page.getByRole('button', { name: /say hello/i })).toBeEnabled();
  });

  test('button prevents double-submit while loading', async ({ page }) => {
    await mockHealthyBackend(page);

    let resolvePost!: () => void;
    const postPending = new Promise<void>((res) => {
      resolvePost = res;
    });

    await page.route('**/api/hello', async (route) => {
      if (route.request().method() === 'POST') {
        await postPending;
        return route.fulfill({ json: { message: 'Hello, Alice!' } });
      }
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('Alice');

    // Count outgoing POST requests
    let postCount = 0;
    page.on('request', (req) => {
      if (req.method() === 'POST' && req.url().includes('/api/hello')) postCount++;
    });

    await page.getByRole('button', { name: /say hello/i }).click();

    // Button is now disabled — a second click must be ignored
    await expect(page.getByRole('button', { name: /sending/i })).toBeDisabled();
    await page.getByRole('button', { name: /sending/i }).click({ force: true });

    resolvePost();
    await expect(page.getByRole('button', { name: /say hello/i })).toBeEnabled();

    // Only one POST must have been made
    expect(postCount).toBe(1);
  });

  test('empty name does not trigger a POST', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    let postMade = false;
    page.on('request', (req) => {
      if (req.method() === 'POST' && req.url().includes('/api/hello')) postMade = true;
    });

    await page.getByRole('button', { name: /say hello/i }).click();
    // Short pause to let any accidental request fire
    await page.waitForTimeout(200); // only timeout allowed — ensures no accidental POST

    expect(postMade).toBe(false);
  });

  test('whitespace-only name does not trigger a POST', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    let postMade = false;
    page.on('request', (req) => {
      if (req.method() === 'POST' && req.url().includes('/api/hello')) postMade = true;
    });

    await page.getByPlaceholder('Enter your name').fill('   ');
    await page.getByRole('button', { name: /say hello/i }).click();
    await page.waitForTimeout(200);

    expect(postMade).toBe(false);
  });

  test('shows error message when POST fails with network error', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.route('**/api/hello', (route) => {
      if (route.request().method() === 'POST') return route.abort('failed');
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('Alice');
    await page.getByRole('button', { name: /say hello/i }).click();

    // Wait for error state — driven by the aborted request response, not time
    await expect(page.getByText('Error connecting to API')).toBeVisible();
  });

  test('shows error and re-enables form after failed submission', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.route('**/api/hello', (route) => {
      if (route.request().method() === 'POST') return route.abort('failed');
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('Alice');
    await page.getByRole('button', { name: /say hello/i }).click();

    await expect(page.getByText('Error connecting to API')).toBeVisible();
    // Form must be re-enabled after the error — no manual timeout needed
    await expect(page.getByRole('button', { name: /say hello/i })).toBeEnabled();
  });

  test('submits form with Enter key', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.route('**/api/hello', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({ json: { message: 'Hello, KeyboardUser!' } });
      }
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('KeyboardUser');
    await page.getByPlaceholder('Enter your name').press('Enter');

    await expect(page.getByText('Hello, KeyboardUser!')).toBeVisible();
  });

  test('sends correct JSON body in POST request', async ({ page }) => {
    await mockHealthyBackend(page);

    let capturedBody: Record<string, unknown> | null = null;
    await page.route('**/api/hello', async (route) => {
      if (route.request().method() === 'POST') {
        capturedBody = JSON.parse(route.request().postData() ?? '{}');
        return route.fulfill({ json: { message: 'Hello, TestUser!' } });
      }
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('TestUser');

    const [response] = await Promise.all([
      page.waitForResponse('**/api/hello'),
      page.getByRole('button', { name: /say hello/i }).click(),
    ]);

    expect(response.status()).toBe(200);
    expect(capturedBody).toEqual({ name: 'TestUser' });
  });
});

// ---------------------------------------------------------------------------
// API contract: forward-compatibility
// ---------------------------------------------------------------------------

test.describe('api contract', () => {
  test('displays only version field from /api/version response', async ({ page }) => {
    await page.route('**/health', (route) => route.fulfill({ json: { status: 'healthy' } }));
    await page.route('**/api/version', (route) =>
      route.fulfill({
        json: { version: '2.5.0', name: 'software-factory-api', environment: 'production' },
      })
    );
    await page.route('**/api/hello', (route) =>
      route.fulfill({ json: { message: 'Hello, World!' } })
    );

    await page.goto('/');

    await expect(page.getByText('2.5.0')).toBeVisible();
    await expect(page.getByText('software-factory-api')).not.toBeVisible();
    await expect(page.getByText('production')).not.toBeVisible();
  });

  test('handles extra fields in API responses without breaking', async ({ page }) => {
    await page.route('**/health', (route) =>
      route.fulfill({ json: { status: 'healthy', uptime: 9999, region: 'us-east-1' } })
    );
    await page.route('**/api/version', (route) =>
      route.fulfill({ json: { version: '3.0.0', build: 'abc', commit: 'def' } })
    );
    await page.route('**/api/hello', (route) =>
      route.fulfill({ json: { message: 'Hello, World!', requestId: 'xyz', ts: '2026-01-01' } })
    );

    await page.goto('/');

    await expect(page.getByText('Connected')).toBeVisible();
    await expect(page.getByText('3.0.0')).toBeVisible();
  });

  test('shows error when POST returns HTTP 422', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.route('**/api/hello', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 422,
          json: { detail: [{ loc: ['body', 'name'], msg: 'Field required' }] },
        });
      }
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('Alice');
    await page.getByRole('button', { name: /say hello/i }).click();

    await expect(page.getByText('Error connecting to API')).toBeVisible();
  });

  test('shows error when POST returns HTTP 500', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.route('**/api/hello', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({ status: 500, json: { error: 'Internal Server Error' } });
      }
      return route.fulfill({ json: { message: 'Hello, World!' } });
    });

    await page.goto('/');
    await expect(page.getByText('Connected')).toBeVisible();

    await page.getByPlaceholder('Enter your name').fill('Alice');
    await page.getByRole('button', { name: /say hello/i }).click();

    await expect(page.getByText('Error connecting to API')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Navigation & links
// ---------------------------------------------------------------------------

test.describe('navigation', () => {
  test('Claude Code link points to github.com/anthropics', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    const claudeLink = page.getByRole('link', { name: 'Claude Code' });
    await expect(claudeLink).toHaveAttribute('href', /github\.com\/anthropics/);
    await expect(claudeLink).toHaveAttribute('target', '_blank');
  });

  test('API Docs link points to /docs', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    const docsLink = page.getByRole('link', { name: 'API Docs' });
    await expect(docsLink).toHaveAttribute('href', '/docs');
  });

  test('View Source link has target _blank', async ({ page }) => {
    await mockHealthyBackend(page);
    await page.goto('/');

    const sourceLink = page.getByRole('link', { name: 'View Source' });
    await expect(sourceLink).toHaveAttribute('target', '_blank');
  });
});
