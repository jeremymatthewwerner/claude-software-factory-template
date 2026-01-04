import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Home from '@/app/page';

// Mock fetch
global.fetch = jest.fn();

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
    it('renders the title', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      expect(screen.getByText('Software Factory')).toBeInTheDocument();
    });

    it('renders the subtitle', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      expect(screen.getByText('Autonomous development powered by Claude')).toBeInTheDocument();
    });

    it('renders the API status section', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      expect(screen.getByText('API Status')).toBeInTheDocument();
    });

    it('renders the form', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      expect(screen.getByPlaceholderText('Enter your name')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /say hello/i })).toBeInTheDocument();
    });
  });

  describe('API status check', () => {
    it('shows connected status when API is healthy', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Connected')).toBeInTheDocument();
      });
    });

    it('shows version when API is healthy', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

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
    it('allows typing a name', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

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
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
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

    it('disables input when API is disconnected', async () => {
      (global.fetch as jest.Mock).mockRejectedValue(new Error('Network error'));

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText('Enter your name');
      expect(input).toBeDisabled();
    });

    it('disables button when API is disconnected', async () => {
      (global.fetch as jest.Mock).mockRejectedValue(new Error('Network error'));

      render(<Home />);

      await waitFor(() => {
        expect(screen.getByText('Disconnected')).toBeInTheDocument();
      });

      const button = screen.getByRole('button', { name: /say hello/i });
      expect(button).toBeDisabled();
    });
  });

  describe('info cards', () => {
    it('renders Getting Started section', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      expect(screen.getByText('Getting Started')).toBeInTheDocument();
    });

    it('renders Claude Code card', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      expect(screen.getByText('Claude Code')).toBeInTheDocument();
    });

    it('renders API Docs card', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      expect(screen.getByText('API Docs')).toBeInTheDocument();
    });
  });

  describe('footer', () => {
    it('renders footer with technology links', async () => {
      mockFetch({
        '/health': { status: 'healthy' },
        '/api/version': { version: '0.1.0' },
        '/api/hello': { message: 'Hello, World!' },
      });

      render(<Home />);

      expect(screen.getByText('Next.js')).toBeInTheDocument();
      expect(screen.getByText('FastAPI')).toBeInTheDocument();
      expect(screen.getByText('Claude')).toBeInTheDocument();
    });
  });
});
