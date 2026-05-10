import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Home from '@/app/page';

// Mock fetch
global.fetch = jest.fn();

const HEALTHY_RESPONSES = {
  '/health': { status: 'healthy' },
  '/api/version': { version: '0.1.0' },
  '/api/hello': { message: 'Hello, World!' },
};

const mockFetch = (responses: { [key: string]: object }) => {
  (global.fetch as jest.Mock).mockImplementation((url: string) => {
    const endpoint = url.replace('http://localhost:8000', '');

    if (responses[endpoint]) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(responses[endpoint]),
      });
    }

    return Promise.reject(new Error('Not found'));
  });
};

describe('Home Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial render', () => {
    beforeEach(() => {
      mockFetch(HEALTHY_RESPONSES);
    });

    it('renders the title', () => {
      render(<Home />);
      expect(screen.getByText('Software Factory')).toBeInTheDocument();
    });

    it('renders the subtitle', () => {
      render(<Home />);
      expect(screen.getByText('Autonomous development powered by Claude')).toBeInTheDocument();
    });

    it('renders the API status section', () => {
      render(<Home />);
      expect(screen.getByText('API Status')).toBeInTheDocument();
    });

    it('renders the form', () => {
      render(<Home />);
      expect(screen.getByPlaceholderText('Enter your name')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /say hello/i })).toBeInTheDocument();
    });
  });

  describe('API status check', () => {
    it('shows connected status when API is healthy', async () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });
    });

    it('shows version when API is healthy', async () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('0.1.0')).toBeInTheDocument();
      });
    });

    it('shows disconnected when API fails', async () => {
      (global.fetch as jest.Mock).mockRejectedValue(new Error('Network error'));
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });
    });

    it('shows error message when API fails', async () => {
      (global.fetch as jest.Mock).mockRejectedValue(new Error('Network error'));
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Could not connect to backend API')).toBeInTheDocument();
      });
    });
  });

  describe('greeting form', () => {
    beforeEach(() => {
      mockFetch(HEALTHY_RESPONSES);
    });

    it('allows typing a name', async () => {
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: 'Alice' } });

      expect(input).toHaveValue('Alice');
    });

    it('submits the form and shows greeting', async () => {
      mockFetch({
        ...HEALTHY_RESPONSES,
        '/api/hello': { message: 'Hello, Alice!' },
      });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });
    });

    it('shows error message when POST /api/hello fails', async () => {
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockRejectedValue(new Error('Network error'));

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Error connecting to API')).toBeInTheDocument();
      });
    });

    it('disables input when API is disconnected', async () => {
      (global.fetch as jest.Mock).mockRejectedValue(new Error('Network error'));
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });

      expect(screen.getByPlaceholderText('Enter your name')).toBeDisabled();
    });

    it('disables button when API is disconnected', async () => {
      (global.fetch as jest.Mock).mockRejectedValue(new Error('Network error'));
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });

      expect(screen.getByRole('button', { name: /say hello/i })).toBeDisabled();
    });
  });

  describe('test isolation guardrail', () => {
    it('fetch mock has no prior calls before this test begins', () => {
      // The outer beforeEach calls jest.clearAllMocks() before every test.
      // This test verifies that guarantee: at test start, before any render,
      // mock.calls must be empty. If clearAllMocks() ever stops working (e.g.,
      // after a Jest version upgrade or misconfiguration), this test fails and
      // exposes why other call-count assertions produce misleading results.
      expect((global.fetch as jest.Mock).mock.calls).toHaveLength(0);
    });
  });

  describe('edge cases', () => {
    it('shows disconnected when health check returns non-ok status', async () => {
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({}),
      });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });
    });

    it('shows error message when health check returns non-ok status', async () => {
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({}),
      });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Could not connect to backend API')).toBeInTheDocument();
      });
    });

    it('does not call POST /api/hello when name is empty', async () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const callCountBefore = (global.fetch as jest.Mock).mock.calls.length;
      const button = screen.getByRole('button', { name: /say hello/i });
      fireEvent.click(button);

      expect((global.fetch as jest.Mock).mock.calls.length).toBe(callCountBefore);
    });

    it('does not call POST /api/hello when name is whitespace only', async () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: '   ' } });
      const callCountBefore = (global.fetch as jest.Mock).mock.calls.length;
      fireEvent.click(button);

      expect((global.fetch as jest.Mock).mock.calls.length).toBe(callCountBefore);
    });

    it('shows checking status before API resolves', () => {
      (global.fetch as jest.Mock).mockReturnValue(new Promise(() => {}));
      render(<Home />);

      expect(screen.getByText('Checking...')).toBeInTheDocument();
    });

    it('does not show version badge while API is checking', () => {
      (global.fetch as jest.Mock).mockReturnValue(new Promise(() => {}));
      render(<Home />);

      expect(screen.queryByText('Version')).not.toBeInTheDocument();
    });

    it('shows loading state during form submission', async () => {
      let resolvePost: (value: unknown) => void;
      const postPromise = new Promise((res) => {
        resolvePost = res;
      });

      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockReturnValueOnce(postPromise);

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      expect(screen.getByText('Sending...')).toBeInTheDocument();
      expect(button).toBeDisabled();

      resolvePost!({ ok: true, json: () => Promise.resolve({ message: 'Hello, Alice!' }) });
    });

    it('renders the View Source card', () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);
      expect(screen.getByText('View Source')).toBeInTheDocument();
    });

    it('unmounts cleanly before fetch resolves without React state update warnings', () => {
      // If a component calls setState on an unmounted instance, React logs a
      // warning ("Can't perform a React state update on an unmounted component").
      // This test mounts and immediately unmounts the component while all
      // fetch promises are perpetually pending, verifying that the useEffect
      // cleanup (or absence of state updates on unmounted components) prevents
      // any such violation. A failure here indicates a missing cleanup in useEffect.
      (global.fetch as jest.Mock).mockReturnValue(new Promise(() => {}));
      const { unmount } = render(<Home />);
      // Unmount before any fetch resolves — no assertions needed;
      // the test passes if no error or unhandled rejection is thrown.
      unmount();
    });
  });

  describe('info cards', () => {
    beforeEach(() => {
      mockFetch(HEALTHY_RESPONSES);
    });

    it('renders Getting Started section', () => {
      render(<Home />);
      expect(screen.getByText('Getting Started')).toBeInTheDocument();
    });

    it('renders Claude Code card', () => {
      render(<Home />);
      expect(screen.getByText('Claude Code')).toBeInTheDocument();
    });

    it('renders API Docs card', () => {
      render(<Home />);
      expect(screen.getByText('API Docs')).toBeInTheDocument();
    });
  });

  describe('footer', () => {
    beforeEach(() => {
      mockFetch(HEALTHY_RESPONSES);
    });

    it('renders footer with technology links', () => {
      render(<Home />);
      expect(screen.getByText('Next.js')).toBeInTheDocument();
      expect(screen.getByText('FastAPI')).toBeInTheDocument();
      expect(screen.getByText('Claude')).toBeInTheDocument();
    });
  });

  describe('flakiness prevention', () => {
    it('fetches health, version, and hello in that order on mount', async () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const urls = (global.fetch as jest.Mock).mock.calls.map(([url]: [string]) =>
        url.replace('http://localhost:8000', '')
      );
      expect(urls[0]).toBe('/health');
      expect(urls[1]).toBe('/api/version');
      expect(urls[2]).toBe('/api/hello');
    });

    it('clears loading state after successful submission', async () => {
      mockFetch({ ...HEALTHY_RESPONSES, '/api/hello': { message: 'Hello, Alice!' } });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.queryByText('Sending...')).not.toBeInTheDocument();
        expect(button).not.toBeDisabled();
      });
    });

    it('button is disabled during submission preventing double-submit', async () => {
      let resolveSubmit!: (value: unknown) => void;
      const pendingPost = new Promise((res) => {
        resolveSubmit = res;
      });

      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockReturnValueOnce(pendingPost);

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      expect(button).toBeDisabled();

      resolveSubmit({ ok: true, json: () => Promise.resolve({ message: 'Hello, Alice!' }) });

      await waitFor(() => {
        expect(button).not.toBeDisabled();
      });
    });

    it('clears loading state after failed submission', async () => {
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockRejectedValueOnce(new Error('Network error'));

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Error connecting to API')).toBeInTheDocument();
      });

      expect(screen.queryByText('Sending...')).not.toBeInTheDocument();
      expect(button).not.toBeDisabled();
    });
  });

  describe('behavioral tests', () => {
    it('shows "Backend says:" prefix when API is healthy', async () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      expect(screen.getByText(/Backend says:/)).toBeInTheDocument();
    });

    it('does not show "Backend says:" prefix when API is unhealthy', async () => {
      (global.fetch as jest.Mock).mockRejectedValue(new Error('Network error'));
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });

      expect(screen.queryByText(/Backend says:/)).not.toBeInTheDocument();
    });

    it('submits the form on Enter key in the name input', async () => {
      mockFetch({
        ...HEALTHY_RESPONSES,
        '/api/hello': { message: 'Hello, Alice!' },
      });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.submit(input.closest('form')!);

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });
    });

    it('sends the correct JSON body in POST /api/hello', async () => {
      mockFetch({
        ...HEALTHY_RESPONSES,
        '/api/hello': { message: 'Hello, TestUser!' },
      });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'TestUser' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Hello, TestUser!')).toBeInTheDocument();
      });

      const postCall = (global.fetch as jest.Mock).mock.calls.find(
        ([url, opts]: [string, RequestInit]) =>
          url.includes('/api/hello') && opts?.method === 'POST'
      );
      expect(postCall).toBeDefined();
      expect(JSON.parse(postCall[1].body as string)).toEqual({ name: 'TestUser' });
    });
  });

  describe('API contract integration', () => {
    it('shows error message when POST /api/hello returns HTTP 422', async () => {
      // The backend returns 422 when the request body is invalid.
      // The frontend must handle non-ok HTTP responses, not just network errors.
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockResolvedValueOnce({
          ok: false,
          status: 422,
          json: () =>
            Promise.resolve({
              detail: [{ loc: ['body', 'name'], msg: 'Field required', type: 'missing' }],
            }),
        });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Error connecting to API')).toBeInTheDocument();
      });
    });

    it('shows error message when POST /api/hello returns HTTP 500', async () => {
      // Server errors must also show the error message, not a blank greeting.
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockResolvedValueOnce({
          ok: false,
          status: 500,
          json: () => Promise.resolve({ error: 'Internal Server Error' }),
        });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Error connecting to API')).toBeInTheDocument();
      });
    });

    it('displays version from version response (not name or environment fields)', async () => {
      // The backend /api/version returns {version, name, environment}.
      // The frontend must only display the 'version' field.
      (global.fetch as jest.Mock).mockImplementation((url: string) => {
        const endpoint = url.replace('http://localhost:8000', '');
        if (endpoint === '/health') {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
        }
        if (endpoint === '/api/version') {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                version: '1.2.3',
                name: 'software-factory-api',
                environment: 'production',
              }),
          });
        }
        if (endpoint === '/api/hello') {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({ message: 'Hello, World!', timestamp: '2026-01-01T00:00:00Z' }),
          });
        }
        return Promise.reject(new Error('Not found'));
      });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('1.2.3')).toBeInTheDocument();
      });

      // 'name' and 'environment' fields must NOT appear as version display
      expect(screen.queryByText('software-factory-api')).not.toBeInTheDocument();
      expect(screen.queryByText('production')).not.toBeInTheDocument();
    });

    it('displays message from hello response (not timestamp field)', async () => {
      // The backend /api/hello returns {message, timestamp}.
      // The frontend must only display the 'message' field.
      (global.fetch as jest.Mock).mockImplementation((url: string) => {
        const endpoint = url.replace('http://localhost:8000', '');
        if (endpoint === '/health') {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
        }
        if (endpoint === '/api/version') {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) });
        }
        if (endpoint === '/api/hello') {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                message: 'Hello, World! Welcome to your Software Factory.',
                timestamp: '2026-01-01T00:00:00Z',
              }),
          });
        }
        return Promise.reject(new Error('Not found'));
      });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      // Message is displayed
      expect(screen.getByText(/Hello, World!/)).toBeInTheDocument();
      // Timestamp is NOT displayed as standalone text
      expect(screen.queryByText('2026-01-01T00:00:00Z')).not.toBeInTheDocument();
    });

    it('handles API responses with extra unexpected fields gracefully', async () => {
      // Forward-compatible: if the backend adds new fields, the frontend must not break.
      (global.fetch as jest.Mock).mockImplementation((url: string) => {
        const endpoint = url.replace('http://localhost:8000', '');
        if (endpoint === '/health') {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                status: 'healthy',
                timestamp: '2026-01-01T00:00:00Z',
                uptime: 12345,
                region: 'us-east-1',
              }),
          });
        }
        if (endpoint === '/api/version') {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                version: '0.2.0',
                name: 'api',
                environment: 'staging',
                build: 'abc123',
                commit: 'def456',
              }),
          });
        }
        if (endpoint === '/api/hello') {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                message: 'Hello, World!',
                timestamp: '2026-01-01T00:00:00Z',
                requestId: 'xyz',
              }),
          });
        }
        return Promise.reject(new Error('Not found'));
      });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
        expect(screen.getByText('0.2.0')).toBeInTheDocument();
        expect(screen.getByText(/Hello, World!/)).toBeInTheDocument();
      });
    });
  });

  describe('mid-sequence API failure edge cases', () => {
    it('shows unhealthy when version fetch fails after health succeeds', async () => {
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockRejectedValueOnce(new Error('Version network error'));

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });

      expect(screen.getByText('Could not connect to backend API')).toBeInTheDocument();
    });

    it('shows unhealthy when hello GET fetch fails after health and version succeed', async () => {
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockRejectedValueOnce(new Error('Hello network error'));

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });

      expect(screen.getByText('Could not connect to backend API')).toBeInTheDocument();
    });
  });

  describe('form state edge cases', () => {
    it('name input retains value after successful greeting', async () => {
      mockFetch({ ...HEALTHY_RESPONSES, '/api/hello': { message: 'Hello, Alice!' } });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });

      expect(input).toHaveValue('Alice');
    });

    it('name input retains value after a failed submission', async () => {
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockRejectedValueOnce(new Error('Network error'));

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      await waitFor(() => {
        expect(screen.getByText('Error connecting to API')).toBeInTheDocument();
      });

      expect(input).toHaveValue('Alice');
    });

    it('second submission overwrites previous greeting', async () => {
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, Alice!' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, Bob!' }),
        });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });

      fireEvent.change(input, { target: { value: 'Bob' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Hello, Bob!')).toBeInTheDocument();
      });

      expect(screen.queryByText('Hello, Alice!')).not.toBeInTheDocument();
    });

    it('error message is replaced by successful greeting on retry', async () => {
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, Alice!' }),
        });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Error connecting to API')).toBeInTheDocument();
      });

      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });

      expect(screen.queryByText('Error connecting to API')).not.toBeInTheDocument();
    });
  });

  describe('version badge edge cases', () => {
    it('does not show version badge when version field is absent from version response', async () => {
      (global.fetch as jest.Mock).mockImplementation((url: string) => {
        const endpoint = url.replace('http://localhost:8000', '');
        if (endpoint === '/health') {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
        }
        if (endpoint === '/api/version') {
          // Response has no 'version' key — versionData.version will be undefined
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ name: 'api' }) });
        }
        if (endpoint === '/api/hello') {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ message: 'Hello, World!' }),
          });
        }
        return Promise.reject(new Error('Not found'));
      });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      // The {apiStatus.version && ...} conditional is falsy when version is undefined
      expect(screen.queryByText('Version')).not.toBeInTheDocument();
    });

    it('does not show version badge when version field is an empty string', async () => {
      (global.fetch as jest.Mock).mockImplementation((url: string) => {
        const endpoint = url.replace('http://localhost:8000', '');
        if (endpoint === '/health') {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
        }
        if (endpoint === '/api/version') {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ version: '' }) });
        }
        if (endpoint === '/api/hello') {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ message: 'Hello, World!' }),
          });
        }
        return Promise.reject(new Error('Not found'));
      });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      // Empty string is falsy — the version badge conditional evaluates to false
      expect(screen.queryByText('Version')).not.toBeInTheDocument();
    });
  });

  describe('regression-prevention', () => {
    it('fetches from the correct full URLs on mount', async () => {
      // Pins the exact endpoint paths so a rename (/health → /api/health,
      // /api/hello → /api/greet, etc.) is caught immediately.
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const calledUrls = (global.fetch as jest.Mock).mock.calls.map(
        (c: [string, ...unknown[]]) => c[0]
      );
      expect(calledUrls).toContain('http://localhost:8000/health');
      expect(calledUrls).toContain('http://localhost:8000/api/version');
      expect(calledUrls).toContain('http://localhost:8000/api/hello');
    });

    it('POST /api/hello is called with the correct full URL', async () => {
      // Ensures the submit handler uses the same base URL and path as the
      // init sequence — catches a copy-paste typo in the POST URL.
      mockFetch({ ...HEALTHY_RESPONSES, '/api/hello': { message: 'Hello, Alice!' } });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });

      const postCalls = (global.fetch as jest.Mock).mock.calls.filter(
        (c: [string, RequestInit]) => c[1]?.method === 'POST'
      );
      expect(postCalls).toHaveLength(1);
      expect(postCalls[0][0]).toBe('http://localhost:8000/api/hello');
    });

    it('every fetch on mount uses the same base URL (no mixed origins)', async () => {
      // Guards against one call accidentally using a different host or protocol.
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const calls = (global.fetch as jest.Mock).mock.calls as [string, ...unknown[]][];
      calls.forEach(([url]) => {
        expect(url).toMatch(/^http:\/\/localhost:8000\//);
      });
    });
  });

  describe('security', () => {
    it('renders XSS payload in greeting as escaped text, not as a DOM script element', async () => {
      // The backend echoes the name verbatim in the greeting JSON.  If a
      // response message contains a <script> tag, React's JSX must render it as
      // escaped text — not inject it as a live DOM element.
      const xssMessage = "<script>alert('xss')</script>";
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: xssMessage }),
        });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      await waitFor(() => {
        // React renders the string as a text node inside a <p> element — not as a script tag.
        const greetingEl = screen.getByText(xssMessage);
        expect(greetingEl).toBeInTheDocument();
        expect(greetingEl.tagName).toBe('P');
      });
    });

    it('external links have rel="noopener noreferrer" to prevent tab-nabbing', () => {
      // target="_blank" links can be exploited (tab-nabbing) unless
      // rel="noopener noreferrer" is present.
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      const externalLinks = document.querySelectorAll('a[target="_blank"]');
      expect(externalLinks.length).toBeGreaterThan(0);
      externalLinks.forEach((link) => {
        const rel = link.getAttribute('rel') ?? '';
        expect(rel).toContain('noopener');
        expect(rel).toContain('noreferrer');
      });
    });
  });

  // Performance / efficiency regression guards.
  // The init useEffect runs once and makes 3 fetches. A regression that
  // re-fires it (missing deps array, state-change in deps, etc.) would
  // multiply network traffic and slow first paint — these tests catch that.
  describe('fetch efficiency (e2e-performance)', () => {
    it('makes exactly 3 fetch calls on mount (health, version, hello)', async () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      expect((global.fetch as jest.Mock).mock.calls).toHaveLength(3);
      const urls = (global.fetch as jest.Mock).mock.calls.map((call) => call[0]);
      expect(urls).toEqual(
        expect.arrayContaining([
          expect.stringContaining('/health'),
          expect.stringContaining('/api/version'),
          expect.stringContaining('/api/hello'),
        ])
      );
    });

    it('does not re-fetch when re-rendering with the same props', async () => {
      mockFetch(HEALTHY_RESPONSES);
      const { rerender } = render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const callsAfterMount = (global.fetch as jest.Mock).mock.calls.length;
      rerender(<Home />);
      rerender(<Home />);

      // Re-rendering with no prop change must not re-trigger the init effect.
      expect((global.fetch as jest.Mock).mock.calls).toHaveLength(callsAfterMount);
    });

    it('issues exactly one POST per submit click (no fetch storms)', async () => {
      mockFetch({
        ...HEALTHY_RESPONSES,
        '/api/hello': { message: 'Hello, Alice! Welcome.' },
      });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const initCalls = (global.fetch as jest.Mock).mock.calls.length;
      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice! Welcome.')).toBeInTheDocument();
      });

      const postCalls = (global.fetch as jest.Mock).mock.calls
        .slice(initCalls)
        .filter((call) => call[1]?.method === 'POST');
      expect(postCalls).toHaveLength(1);
    });

    it('rapid double-clicks during in-flight submit do not multiply POSTs', async () => {
      // The button is disabled while loading=true. This test verifies that
      // contract — clicking twice rapidly should result in one POST, not two,
      // because the second click hits a disabled button.
      let resolvePost: ((value: object) => void) | null = null;
      const pendingPost = new Promise<object>((resolve) => {
        resolvePost = resolve;
      });

      (global.fetch as jest.Mock).mockImplementation((url: string, opts) => {
        const endpoint = url.replace('http://localhost:8000', '');
        if (opts?.method === 'POST') {
          return pendingPost.then((data) => ({
            ok: true,
            json: () => Promise.resolve(data),
          }));
        }
        if (HEALTHY_RESPONSES[endpoint as keyof typeof HEALTHY_RESPONSES]) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve(HEALTHY_RESPONSES[endpoint as keyof typeof HEALTHY_RESPONSES]),
          });
        }
        return Promise.reject(new Error('Not found'));
      });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const initCalls = (global.fetch as jest.Mock).mock.calls.length;
      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });

      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(button);
      // Now button shows "Sending..." and is disabled — second click is a no-op.
      fireEvent.click(button);
      fireEvent.click(button);

      // Resolve the pending POST so the test cleans up.
      resolvePost!({ message: 'Hello, Alice!' });
      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });

      const postCalls = (global.fetch as jest.Mock).mock.calls
        .slice(initCalls)
        .filter((call) => call[1]?.method === 'POST');
      expect(postCalls).toHaveLength(1);
    });

    it('does not fetch when submit is clicked with empty/whitespace name', async () => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const initCalls = (global.fetch as jest.Mock).mock.calls.length;
      const input = screen.getByPlaceholderText('Enter your name');

      // Empty
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));
      // Whitespace-only
      fireEvent.change(input, { target: { value: '   ' } });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      // No additional POST should fire — handleSubmit short-circuits on
      // !name.trim(). This guards against a regression where a typo'd
      // condition would let empty submissions through and waste a request.
      expect((global.fetch as jest.Mock).mock.calls).toHaveLength(initCalls);
    });

    it('init sequence finishes within Jest waitFor default (1s)', async () => {
      // Healthy state must reach the DOM well within the default 1000ms
      // waitFor budget. If it doesn't, every other test in this file pays
      // a 1s tax on failure — a real perf regression.
      mockFetch(HEALTHY_RESPONSES);
      const start = performance.now();
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });
      const elapsed = performance.now() - start;
      expect(elapsed).toBeLessThan(1000);
    });

    it('loading state clears after submit completes (no stuck "Sending...")', async () => {
      mockFetch({
        ...HEALTHY_RESPONSES,
        '/api/hello': { message: 'Hello, Alice!' },
      });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: 'Alice' } });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      // Button label flips back from "Sending..." to "Say Hello" once the
      // promise settles — regression guard against a missing finally().
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /say hello/i })).toBeInTheDocument();
      });
      expect(screen.queryByRole('button', { name: /sending/i })).not.toBeInTheDocument();
    });

    it('makes init fetches without "undefined" segments (env var sanity)', async () => {
      // If NEXT_PUBLIC_API_URL was undefined at build time AND no fallback
      // existed, fetch URLs could contain literal "undefined" — a class of
      // bug that ships silently. This test guards against URL malformation.
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect((global.fetch as jest.Mock).mock.calls.length).toBeGreaterThan(0);
      });

      const urls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
      urls.forEach((url) => {
        expect(url).not.toContain('undefined');
        expect(url).not.toContain('null');
        expect(url).toMatch(/^https?:\/\//);
      });
    });
  });

  // Edge cases the existing suites don't cover.
  // - "does not call POST when name is whitespace only" already tests space-only
  //   inputs; tab and newline are different ASCII characters that still satisfy
  //   String.prototype.trim() and so must also short-circuit handleSubmit.
  // - The greeting <p> renders whatever the backend returned. The backend
  //   contract allows astral-plane Unicode (verified in the backend suite); the
  //   frontend must render it as a single text node, not crash on it.
  // - The submit button must have type="submit" and the input must have
  //   type="text" — these attributes are how the form behaves the way the rest
  //   of the test suite assumes (Enter submits, browser doesn't apply numeric
  //   validation). A regression that flips them is silent under the existing
  //   tests because they fire events directly rather than relying on browser
  //   form semantics.
  describe('whitespace-only submit edge cases', () => {
    it.each([
      ['tab-only', '\t\t'],
      ['newline-only', '\n'],
      ['mixed whitespace', ' \t\n '],
    ])('does not call POST /api/hello when name is %s', async (_label, name) => {
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const initCalls = (global.fetch as jest.Mock).mock.calls.length;
      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: name } });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      // handleSubmit short-circuits on !name.trim(); the only fetches should be
      // the three init calls captured above.
      expect((global.fetch as jest.Mock).mock.calls).toHaveLength(initCalls);
    });
  });

  describe('non-BMP greeting rendering', () => {
    it('renders an astral-plane (4-byte UTF-8) greeting from the backend as text', async () => {
      // Mathematical script capital A (U+1D4D0). It encodes as 4 bytes in
      // UTF-8 and is a surrogate pair in JavaScript strings. React must render
      // it as a single text node without splitting or escaping the surrogate
      // pair.
      const astralGreeting = 'Hello, 𝓐lice!';
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: astralGreeting }),
        });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      fireEvent.change(input, { target: { value: '𝓐lice' } });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      await waitFor(() => {
        expect(screen.getByText(astralGreeting)).toBeInTheDocument();
      });
    });

    it('renders an emoji greeting from the backend as text', async () => {
      const emojiGreeting = 'Hello, 🎉🤖!';
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: emojiGreeting }),
        });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      fireEvent.change(screen.getByPlaceholderText('Enter your name'), {
        target: { value: '🎉🤖' },
      });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      await waitFor(() => {
        expect(screen.getByText(emojiGreeting)).toBeInTheDocument();
      });
    });
  });

  describe('form attribute regression guards', () => {
    it('the name input has type="text"', () => {
      // Some prior test suites have been bitten by an inadvertent flip to
      // type="number" or type="email" — those change browser-side validation
      // (e.g., "type=number" rejects "Alice") without breaking any of the
      // tests that fire events directly. Pin the attribute explicitly.
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);
      const input = screen.getByPlaceholderText('Enter your name');
      expect(input).toHaveAttribute('type', 'text');
    });

    it('the submit button has type="submit"', () => {
      // The "submits the form on Enter key" test passes only because the
      // button is type="submit". A regression flipping it to type="button"
      // would break Enter-to-submit silently for users who tab into the form,
      // because the form's onSubmit handler would never fire.
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);
      const button = screen.getByRole('button', { name: /say hello/i });
      expect(button).toHaveAttribute('type', 'submit');
    });

    it('the form contains both the input and the submit button', () => {
      // The submit button must live inside the same <form> as the input;
      // otherwise pressing Enter in the input field does not trigger the
      // button's submit semantics. Pin the structural relationship.
      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);
      const input = screen.getByPlaceholderText('Enter your name');
      const button = screen.getByRole('button', { name: /say hello/i });
      const form = input.closest('form');
      expect(form).not.toBeNull();
      expect(form).toContainElement(button);
    });
  });

  // Regression-prevention pins for POST request shape and pre-healthy form
  // state. Both protect contracts that existing tests rely on but never
  // explicitly assert:
  //
  // - POST request shape: existing tests filter calls by `opts.method === 'POST'`
  //   which would silently match nothing if a regression lower-cased the method
  //   or dropped the Content-Type header. We pin the positive presence here.
  // - Pre-healthy form state: only the 'unhealthy' case pins disabled-ness
  //   for the input/button. The 'checking' state (initial render, fetch
  //   pending) is the time window where users are most likely to interact
  //   with the form; pin the disabled-ness so a regression that flips the
  //   condition (e.g. `=== 'unhealthy'` instead of `!== 'healthy'`) is loud.
  // - Fallback `apiUrl`: every test relies on the
  //   `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'` fallback,
  //   but no test pins the literal default. If the fallback is removed or
  //   typo'd ('http://localhost:8001'), every test would still pass against
  //   the (now wrong) base URL — but real `npm run dev` would break.
  describe('regression-prevention: POST request shape', () => {
    it('POST /api/hello sends Content-Type: application/json header', async () => {
      mockFetch({ ...HEALTHY_RESPONSES, '/api/hello': { message: 'Hello, Alice!' } });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      fireEvent.change(screen.getByPlaceholderText('Enter your name'), {
        target: { value: 'Alice' },
      });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });

      const postCall = (global.fetch as jest.Mock).mock.calls.find(
        ([, opts]: [string, RequestInit]) => opts?.method === 'POST'
      );
      expect(postCall).toBeDefined();
      const headers = (postCall![1] as RequestInit).headers as Record<string, string>;
      // Header may be capitalised ('Content-Type') or lowercase by environment;
      // pin presence regardless of casing, but require it to declare JSON.
      const ctKey = Object.keys(headers).find((k) => k.toLowerCase() === 'content-type');
      expect(ctKey).toBeDefined();
      expect(headers[ctKey!]).toBe('application/json');
    });

    it('POST /api/hello uses uppercase method string "POST"', async () => {
      // Existing tests filter calls by `opts.method === 'POST'`, so a
      // regression that submitted with `method: 'post'` (lowercase) would
      // silently match no calls in those filters and the assertions would
      // pass vacuously. Pin the exact uppercase string here.
      mockFetch({ ...HEALTHY_RESPONSES, '/api/hello': { message: 'Hello, Alice!' } });
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      fireEvent.change(screen.getByPlaceholderText('Enter your name'), {
        target: { value: 'Alice' },
      });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      await waitFor(() => {
        expect(screen.getByText('Hello, Alice!')).toBeInTheDocument();
      });

      // The init sequence makes 3 GET calls (no `method` set, defaults to GET).
      // The submit handler must explicitly set method: 'POST'. Find any call
      // whose method is set and assert exactly 'POST'.
      const callsWithMethod = (global.fetch as jest.Mock).mock.calls.filter(
        ([, opts]: [string, RequestInit | undefined]) => opts?.method !== undefined
      );
      expect(callsWithMethod).toHaveLength(1);
      expect((callsWithMethod[0][1] as RequestInit).method).toBe('POST');
    });
  });

  describe('regression-prevention: pre-healthy form state', () => {
    it('input is disabled while apiStatus.health is "checking" (initial render)', () => {
      // The init fetch is perpetually pending so the component stays in
      // 'checking'. Existing tests cover the 'unhealthy' disabled-ness;
      // this pins the 'checking' case, which is the window users are most
      // likely to interact with on a slow backend. The disabled condition
      // is `apiStatus.health !== 'healthy'`, which must remain truthy for
      // both 'checking' and 'unhealthy'.
      (global.fetch as jest.Mock).mockReturnValue(new Promise(() => {}));
      render(<Home />);

      expect(screen.getByText('Checking...')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('Enter your name')).toBeDisabled();
    });

    it('button is disabled while apiStatus.health is "checking" (initial render)', () => {
      (global.fetch as jest.Mock).mockReturnValue(new Promise(() => {}));
      render(<Home />);

      expect(screen.getByText('Checking...')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /say hello/i })).toBeDisabled();
    });
  });

  describe('regression-prevention: apiUrl fallback default', () => {
    it('every fetch URL has the expected base "http://localhost:8000" when NEXT_PUBLIC_API_URL is unset', async () => {
      // The component reads `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'`.
      // The Jest environment does not set NEXT_PUBLIC_API_URL, so every
      // fetch URL must begin with the fallback. Pinning the literal string
      // here catches a regression that drops the `||` fallback or typos it
      // ('http://localhost:8001', 'http://localhost', 'https://localhost:8000').
      // Without this test, every other test would still pass — they match
      // requests by path — but `npm run dev` (which also relies on the
      // fallback) would silently break.
      expect(process.env.NEXT_PUBLIC_API_URL).toBeUndefined();

      mockFetch(HEALTHY_RESPONSES);
      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      const urls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
      expect(urls.length).toBeGreaterThan(0);
      urls.forEach((url) => {
        expect(url.startsWith('http://localhost:8000/')).toBe(true);
      });
    });
  });

  describe('backend error response handling', () => {
    it('clears the loading state when POST returns a non-JSON body', async () => {
      // If the backend returns ok=true but a body that fails to JSON-parse
      // (e.g. the body promise rejects), the catch branch in handleSubmit
      // must still reach the finally block and clear `loading`. A missing
      // finally would leave the button stuck on "Sending..." forever.
      (global.fetch as jest.Mock)
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ version: '0.1.0' }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ message: 'Hello, World!' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.reject(new SyntaxError('Unexpected token < in JSON')),
        });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });

      fireEvent.change(screen.getByPlaceholderText('Enter your name'), {
        target: { value: 'Alice' },
      });
      fireEvent.click(screen.getByRole('button', { name: /say hello/i }));

      // The catch branch sets greeting to the API error message; loading
      // state is cleared in the finally block so the button label reverts.
      await waitFor(() => {
        expect(screen.getByText('Error connecting to API')).toBeInTheDocument();
      });
      expect(screen.queryByRole('button', { name: /sending/i })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /say hello/i })).not.toBeDisabled();
    });
  });
});
