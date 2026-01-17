/**
 * Tests for Repository Status Manager
 */

import { RepositoryStatusManager } from '../src/utils/repo-status-manager';

// Mock the WebClient
const mockWebClient = {
  users: {
    profile: {
      set: jest.fn()
    }
  }
};

describe('RepositoryStatusManager', () => {
  let statusManager: RepositoryStatusManager;

  beforeEach(() => {
    // Create a new instance for each test
    statusManager = new (RepositoryStatusManager as any)('mock-token');
    (statusManager as any).client = mockWebClient;
    jest.clearAllMocks();
  });

  describe('extractRepoName', () => {
    test('extracts repo name from working directory paths', () => {
      const extractRepoName = (statusManager as any).extractRepoName.bind(statusManager);

      expect(extractRepoName('/repos/claude-software-factory-template')).toBe('claude-software-factory-template');
      expect(extractRepoName('/tmp/repo')).toBe(null); // Skip 'repo' as it's a common directory
      expect(extractRepoName('/path/to/my-project')).toBe('my-project');
      expect(extractRepoName('/workspace/backend')).toBe('backend');
      expect(extractRepoName('')).toBe(null);
      expect(extractRepoName('/')).toBe(null);
    });
  });

  describe('getEmojiForRepo', () => {
    test('returns appropriate emojis for repo patterns', () => {
      const getEmojiForRepo = (statusManager as any).getEmojiForRepo.bind(statusManager);

      expect(getEmojiForRepo('claude-software-factory-template')).toBe('🏭');
      expect(getEmojiForRepo('backend-api')).toBe('⚙️');
      expect(getEmojiForRepo('frontend-web')).toBe('🎨');
      expect(getEmojiForRepo('mobile-app')).toBe('📱');
      expect(getEmojiForRepo('api-server')).toBe('🔌');
      expect(getEmojiForRepo('docs-site')).toBe('📚');
      expect(getEmojiForRepo('deployment-scripts')).toBe('🚀');
      expect(getEmojiForRepo('random-project')).toBe('💻');
    });
  });

  describe('generateStatusText', () => {
    test('generates appropriate status text for repositories', () => {
      const generateStatusText = (statusManager as any).generateStatusText.bind(statusManager);

      expect(generateStatusText('my-project')).toBe('Working in my-project');
      expect(generateStatusText('my-project', 'feature-branch')).toBe('Working in my-project:feature-branch');
      expect(generateStatusText('my-project', 'main')).toBe('Working in my-project');

      // Test truncation for long repo names
      const longRepo = 'a'.repeat(40);
      const result = generateStatusText(longRepo);
      expect(result.length).toBeLessThanOrEqual(100); // Status text limit
      expect(result).toContain('...');
    });
  });

  describe('shouldSkipUpdate', () => {
    test('skips update when content hasnt changed', () => {
      const shouldSkipUpdate = (statusManager as any).shouldSkipUpdate.bind(statusManager);

      // Set cache state
      (statusManager as any).cache = {
        lastRepo: 'my-project',
        lastText: 'Working in my-project',
        lastEmoji: '💻',
        lastUpdate: new Date()
      };

      expect(shouldSkipUpdate('my-project')).toBe(true);
      expect(shouldSkipUpdate('different-project')).toBe(false);
    });

    test('skips update when too recent', () => {
      const shouldSkipUpdate = (statusManager as any).shouldSkipUpdate.bind(statusManager);

      // Set cache state with recent update
      const recentTime = new Date();
      (statusManager as any).cache = {
        lastRepo: 'my-project',
        lastText: 'Working in my-project',
        lastEmoji: '💻',
        lastUpdate: recentTime
      };

      expect(shouldSkipUpdate('different-project')).toBe(true);

      // Set cache state with old update
      const oldTime = new Date(Date.now() - 10 * 60 * 1000); // 10 minutes ago
      (statusManager as any).cache = {
        lastRepo: 'my-project',
        lastText: 'Working in my-project',
        lastEmoji: '💻',
        lastUpdate: oldTime
      };

      expect(shouldSkipUpdate('different-project')).toBe(false);
    });
  });

  describe('updateRepoStatus', () => {
    test('successfully updates repo status', async () => {
      mockWebClient.users.profile.set.mockResolvedValue({ ok: true });

      const result = await statusManager.updateRepoStatus({
        repoName: 'test-repo',
        branch: 'main'
      });

      expect(result).toBe(true);
      expect(mockWebClient.users.profile.set).toHaveBeenCalledWith({
        profile: {
          status_text: 'Working in test-repo',
          status_emoji: '💻',
          status_expiration: 0
        }
      });
    });

    test('handles API failures gracefully', async () => {
      mockWebClient.users.profile.set.mockResolvedValue({ ok: false, error: 'rate_limited' });

      const result = await statusManager.updateRepoStatus({
        repoName: 'test-repo'
      });

      expect(result).toBe(false);
    });

    test('handles API errors gracefully', async () => {
      mockWebClient.users.profile.set.mockRejectedValue(new Error('Network error'));

      const result = await statusManager.updateRepoStatus({
        repoName: 'test-repo'
      });

      expect(result).toBe(false);
    });
  });

  describe('updateFromWorkingDirectory', () => {
    test('updates status from working directory path', async () => {
      mockWebClient.users.profile.set.mockResolvedValue({ ok: true });

      const result = await statusManager.updateFromWorkingDirectory('/repos/my-awesome-project');

      expect(result).toBe(true);
      expect(mockWebClient.users.profile.set).toHaveBeenCalledWith({
        profile: {
          status_text: 'Working in my-awesome-project',
          status_emoji: '💻',
          status_expiration: 0
        }
      });
    });

    test('returns false when no repo name can be extracted', async () => {
      const result = await statusManager.updateFromWorkingDirectory('/tmp/repo');

      expect(result).toBe(false);
      expect(mockWebClient.users.profile.set).not.toHaveBeenCalled();
    });
  });

  describe('setCustomStatus', () => {
    test('sets custom status with default emoji', async () => {
      mockWebClient.users.profile.set.mockResolvedValue({ ok: true });

      const result = await statusManager.setCustomStatus('Factory Analysis');

      expect(result).toBe(true);
      expect(mockWebClient.users.profile.set).toHaveBeenCalledWith({
        profile: {
          status_text: 'Factory Analysis',
          status_emoji: '🤖',
          status_expiration: 0
        }
      });
    });

    test('sets custom status with custom emoji and expiration', async () => {
      mockWebClient.users.profile.set.mockResolvedValue({ ok: true });

      const result = await statusManager.setCustomStatus('Debugging', '🔧', 3600);

      expect(result).toBe(true);
      expect(mockWebClient.users.profile.set).toHaveBeenCalledWith({
        profile: {
          status_text: 'Debugging',
          status_emoji: '🔧',
          status_expiration: 3600
        }
      });
    });
  });

  describe('clearStatus', () => {
    test('clears status successfully', async () => {
      mockWebClient.users.profile.set.mockResolvedValue({ ok: true });

      const result = await statusManager.clearStatus();

      expect(result).toBe(true);
      expect(mockWebClient.users.profile.set).toHaveBeenCalledWith({
        profile: {
          status_text: '',
          status_emoji: '',
          status_expiration: 0
        }
      });
    });
  });
});