import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api.config';
import { describeHttpError } from './api-error';
import { AgentSearchResponse } from './models';

export interface ChatTurn {
  id: number;
  query: string;
  askedAt: Date;
  status: 'loading' | 'done' | 'error';
  response?: AgentSearchResponse;
  error?: string;
}

/** The search thread. Each question is an independent agent run on the backend. */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly http = inject(HttpClient);
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
    } catch (error) {
      this.patch(id, { status: 'error', error: describeHttpError(error) });
    }
  }

  private patch(id: number, changes: Partial<ChatTurn>): void {
    this.turns.update((turns) => turns.map((t) => (t.id === id ? { ...t, ...changes } : t)));
  }
}
