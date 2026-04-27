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
});
