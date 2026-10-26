import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api.config';
import { AgentSearchResponse, SearchHistory, SearchSummary, TokenUsage } from './models';

const PAGE_SIZE = 50;

/** Saved searches (backend SQLite). Reopening one shows the stored answer: no new Claude call. */
@Injectable({ providedIn: 'root' })
export class HistoryStore {
  private readonly http = inject(HttpClient);

  readonly searches = signal<SearchSummary[]>([]);
  readonly totals = signal<{ searches: number; usage: TokenUsage }>({
    searches: 0,
    usage: { input_tokens: 0, output_tokens: 0 },
  });

  async load(): Promise<void> {
    try {
      const history = await firstValueFrom(
        this.http.get<SearchHistory>(`${API_BASE_URL}/searches`, { params: { limit: PAGE_SIZE } }),
      );
      this.searches.set(history.searches);
      this.totals.set({ searches: history.total_searches, usage: history.total_usage });
    } catch {
      // Backend offline: the sidebar already says so.
    }
  }

  /** A search just finished: show it at the top without reloading the list. */
  record(response: AgentSearchResponse): void {
    if (!response.search_id || !response.created_at) {
      return; // not saved (e.g. empty library, or history unavailable)
    }
    const summary: SearchSummary = {
      search_id: response.search_id,
      query: response.query,
      created_at: response.created_at,
      match_count: response.matches.length,
      usage: response.usage,
    };
    this.searches.update((list) => [summary, ...list].slice(0, PAGE_SIZE));
    this.totals.update(({ searches, usage }) => ({
      searches: searches + 1,
      usage: {
        input_tokens: usage.input_tokens + response.usage.input_tokens,
        output_tokens: usage.output_tokens + response.usage.output_tokens,
      },
    }));
  }

  get(searchId: string): Promise<AgentSearchResponse> {
    return firstValueFrom(this.http.get<AgentSearchResponse>(`${API_BASE_URL}/searches/${searchId}`));
  }

  async remove(searchId: string): Promise<void> {
    try {
      await firstValueFrom(this.http.delete(`${API_BASE_URL}/searches/${searchId}`));
    } finally {
      await this.load(); // totals change too; also tidies up if it was already gone
    }
  }

  async clear(): Promise<void> {
    await firstValueFrom(this.http.delete(`${API_BASE_URL}/searches`));
    this.searches.set([]);
    this.totals.set({ searches: 0, usage: { input_tokens: 0, output_tokens: 0 } });
  }
}
