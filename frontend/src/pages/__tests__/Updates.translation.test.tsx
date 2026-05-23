import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useUIStore } from '@/stores/uiStore';
import * as updatesApi from '@/api/updates';
import Updates from '@/pages/Updates';
import type { UpdateEvent, ModItem } from '@/types';

vi.mock('@/api/updates');
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const baseMod: ModItem = {
  id: 200,
  source: 'nexusmods',
  external_id: 'nexus-200',
  game: 'Skyrim',
  title: 'Updated Mod',
  url: 'https://example.com/updated-mod',
  author: 'Author Name',
  tags_json: '[]',
  original_summary: 'Original English summary text.',
  translated_summary: '这是更新 Mod 的翻译摘要。',
  version: '2.0.0',
  ignored: false,
  first_seen_at: '2025-01-01T00:00:00Z',
  last_seen_at: '2025-06-01T00:00:00Z',
};

const makeEvent = (overrides: Partial<UpdateEvent> = {}): UpdateEvent => ({
  id: 10,
  modId: 200,
  oldVersion: '1.0.0',
  newVersion: '2.0.0',
  oldUpdatedAt: '2025-01-01T00:00:00Z',
  newUpdatedAt: '2025-06-01T00:00:00Z',
  rawChangelog: 'Added new features.',
  changeSummary: 'Major update with new features',
  detectedAt: '2025-06-01T12:00:00Z',
  seen: false,
  mod: { ...baseMod },
  ...overrides,
});

const makeResponse = (items: UpdateEvent[]) => ({
  items,
  total: items.length,
});

describe('Updates - translated_summary display', () => {
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

  function renderUpdates() {
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
          <Updates />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('displays translated_summary when summaryMode is "bilingual"', async () => {
    useUIStore.setState({ summaryMode: 'bilingual' });
    vi.mocked(updatesApi.fetchUpdates).mockResolvedValue(
      makeResponse([makeEvent()]),
    );

    renderUpdates();

    await waitFor(() => {
      expect(screen.getByText('这是更新 Mod 的翻译摘要。')).toBeInTheDocument();
    });
  });

  it('displays translated_summary when summaryMode is "translated"', async () => {
    useUIStore.setState({ summaryMode: 'translated' });
    vi.mocked(updatesApi.fetchUpdates).mockResolvedValue(
      makeResponse([makeEvent()]),
    );

    renderUpdates();

    await waitFor(() => {
      expect(screen.getByText('这是更新 Mod 的翻译摘要。')).toBeInTheDocument();
    });
  });

  it('does NOT display translated_summary when summaryMode is "original"', async () => {
    useUIStore.setState({ summaryMode: 'original' });
    vi.mocked(updatesApi.fetchUpdates).mockResolvedValue(
      makeResponse([makeEvent()]),
    );

    renderUpdates();

    await waitFor(() => {
      expect(screen.getByText('Updated Mod')).toBeInTheDocument();
    });

    expect(screen.queryByText('这是更新 Mod 的翻译摘要。')).not.toBeInTheDocument();
  });

  it('does NOT display translated_summary when mod has no translated_summary field', async () => {
    useUIStore.setState({ summaryMode: 'bilingual' });
    vi.mocked(updatesApi.fetchUpdates).mockResolvedValue(
      makeResponse([
        makeEvent({
          mod: { ...baseMod, translated_summary: undefined },
        }),
      ]),
    );

    renderUpdates();

    await waitFor(() => {
      expect(screen.getByText('Updated Mod')).toBeInTheDocument();
    });

    expect(screen.queryByText('这是更新 Mod 的翻译摘要。')).not.toBeInTheDocument();
  });

  it('still shows mod title and version regardless of summaryMode', async () => {
    useUIStore.setState({ summaryMode: 'original' });
    vi.mocked(updatesApi.fetchUpdates).mockResolvedValue(
      makeResponse([makeEvent()]),
    );

    renderUpdates();

    await waitFor(() => {
      expect(screen.getByText('Updated Mod')).toBeInTheDocument();
      expect(screen.getByText('1.0.0')).toBeInTheDocument();
      expect(screen.getByText('2.0.0')).toBeInTheDocument();
    });
  });
});
