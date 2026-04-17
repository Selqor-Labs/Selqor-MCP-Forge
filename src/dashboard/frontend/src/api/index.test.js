import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './index';

describe('api()', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('parses successful JSON responses', async () => {
    const response = {
      ok: true,
      text: vi.fn().mockResolvedValue('{"ok":true}'),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

    await expect(api('/api/dashboard')).resolves.toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledWith(
      '/api/dashboard',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('surfaces a helpful timeout error on abort', async () => {
    const error = new Error('aborted');
    error.name = 'AbortError';
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(error));

    await expect(api('/api/dashboard')).rejects.toThrow(
      'Request timed out. Check the dashboard backend and database connection.',
    );
  });
});
