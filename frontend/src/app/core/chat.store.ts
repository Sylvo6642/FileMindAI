import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api.config';
import { describeHttpError } from './api-error';
import { HistoryStore } from './history.store';
import { AgentSearchResponse } from './models';

export interface ChatTurn {
  id: number;
  query: string;
  askedAt: Date;
  status: 'loading' | 'done' | 'error';
  response?: AgentSearchResponse;
  error?: string;
  /** Opened from history: the stored answer, not a fresh search. */
  saved?: boolean;
}

/** The search thread. Each question is an independent agent run on the backend. */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly http = inject(HttpClient);
  private readonly history = inject(HistoryStore);
  private nextId = 1;

  readonly turns = signal<ChatTurn[]>([]);
  readonly busy = computed(() => this.turns().some((turn) => turn.status === 'loading'));

  ask(query: string): void {
    const trimmed = query.trim();
    if (!trimmed || this.busy()) {
      return;
    }
    const turn: ChatTurn = { id: this.nextId++, query: trimmed, askedAt: new Date(), status: 'loading' };
    this.turns.update((turns) => [...turns, turn]);
    void this.run(turn.id, trimmed);
  }

  retry(id: number): void {
    const turn = this.turns().find((t) => t.id === id);
    if (!turn || this.busy()) {
      return;
    }
    this.patch(id, { status: 'loading', error: undefined, askedAt: new Date() });
    void this.run(id, turn.query);
  }

  /**
   * Show a saved search. If it is already in the thread, returns that turn;
   * otherwise the thread is replaced by the stored answer (no Claude call).
   * Returns the turn id to scroll to, or null if it could not be shown.
   */
  async open(searchId: string): Promise<number | null> {
    const existing = this.turns().find((t) => t.response?.search_id === searchId);
    if (existing) {
      return existing.id;
    }
    if (this.busy()) {
      return null;
    }
    try {
      const response = await this.history.get(searchId);
      const turn: ChatTurn = {
        id: this.nextId++,
        query: response.query,
        askedAt: new Date(response.created_at ?? Date.now()),
        status: 'done',
        response,
        saved: true,
      };
      this.turns.set([turn]);
      return turn.id;
    } catch {
      await this.history.load(); // deleted elsewhere: drop it from the list
      return null;
    }
  }

  clear(): void {
    if (!this.busy()) {
      this.turns.set([]);
    }
  }

  private async run(id: number, query: string): Promise<void> {
    try {
      const response = await firstValueFrom(
        this.http.post<AgentSearchResponse>(`${API_BASE_URL}/search`, { query }),
      );
      this.patch(id, { status: 'done', response });
      this.history.record(response);
    } catch (error) {
      this.patch(id, { status: 'error', error: describeHttpError(error) });
    }
  }

  private patch(id: number, changes: Partial<ChatTurn>): void {
    this.turns.update((turns) => turns.map((t) => (t.id === id ? { ...t, ...changes } : t)));
  }
}
