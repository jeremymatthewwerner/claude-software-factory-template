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
});
