import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useUIStore } from '@/stores/uiStore';
import * as favoritesApi from '@/api/favorites';
import Favorites from '@/pages/Favorites';
import type { Favorite, ModItem } from '@/types';

vi.mock('@/api/favorites');
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const baseMod: ModItem = {
  id: 100,
  source: 'nexusmods',
  external_id: 'nexus-100',
  game: 'Skyrim',
  title: 'Test Mod',
  url: 'https://example.com/mod',
  author: 'Test Author',
  tags_json: '[]',
  original_summary: 'This is the original summary.',
  translated_summary: '这是翻译后的摘要内容。',
  version: '1.0.0',
  ignored: false,
  first_seen_at: '2025-01-01T00:00:00Z',
  last_seen_at: '2025-01-01T00:00:00Z',
};

const makeFavorite = (overrides: Partial<Favorite> = {}): Favorite => ({
  id: 1,
  modId: 100,
  trackingEnabled: true,
  notifyOnUpdate: true,
  userNote: '',
  userTags: [],
  lastKnownVersion: '1.0.0',
  lastKnownUpdatedAt: '2025-01-01T00:00:00Z',
  lastCheckedAt: '2025-01-01T00:00:00Z',
  mod: { ...baseMod },
  ...overrides,
});

describe('Favorites - translated_summary display', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    vi.clearAllMocks();
  });

  afterEach(() => {
    queryClient.clear();
  });

  function renderFavorites() {
    return render(
      <QueryClientProvider client={queryClient}>
        <Favorites />
      </QueryClientProvider>,
    );
  }

  it('displays translated_summary when summaryMode is "bilingual"', async () => {
    useUIStore.setState({ summaryMode: 'bilingual' });
    vi.mocked(favoritesApi.fetchFavorites).mockResolvedValue([makeFavorite()]);

    renderFavorites();

    await waitFor(() => {
      // Bilingual mode concatenates translated + original, so use substring match
      expect(screen.getByText(/这是翻译后的摘要内容。/)).toBeInTheDocument();
    });
  });

  it('displays translated_summary when summaryMode is "translated"', async () => {
    useUIStore.setState({ summaryMode: 'translated' });
    vi.mocked(favoritesApi.fetchFavorites).mockResolvedValue([makeFavorite()]);

    renderFavorites();

    await waitFor(() => {
      expect(screen.getByText('这是翻译后的摘要内容。')).toBeInTheDocument();
    });
  });

  it('does NOT display translated_summary when summaryMode is "original"', async () => {
    useUIStore.setState({ summaryMode: 'original' });
    vi.mocked(favoritesApi.fetchFavorites).mockResolvedValue([makeFavorite()]);

    renderFavorites();

    await waitFor(() => {
      expect(screen.getByText('Test Mod')).toBeInTheDocument();
    });

    expect(screen.queryByText('这是翻译后的摘要内容。')).not.toBeInTheDocument();
  });

  it('does NOT display translated_summary when mod has no translated_summary field', async () => {
    useUIStore.setState({ summaryMode: 'bilingual' });
    vi.mocked(favoritesApi.fetchFavorites).mockResolvedValue([
      makeFavorite({
        mod: { ...baseMod, translated_summary: undefined },
      }),
    ]);

    renderFavorites();

    await waitFor(() => {
      expect(screen.getByText('Test Mod')).toBeInTheDocument();
    });

    expect(screen.queryByText('这是翻译后的摘要内容。')).not.toBeInTheDocument();
  });

  it('renders original summary regardless of summaryMode', async () => {
    useUIStore.setState({ summaryMode: 'bilingual' });
    vi.mocked(favoritesApi.fetchFavorites).mockResolvedValue([makeFavorite()]);

    renderFavorites();

    await waitFor(() => {
      expect(screen.getByText('Test Mod')).toBeInTheDocument();
    });
  });
});
