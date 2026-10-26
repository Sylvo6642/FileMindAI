import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api.config';

export type Provider = 'openai' | 'anthropic';

export interface KeyStatus {
  configured: boolean;
  /** Masked, e.g. "sk-…a1B2". The backend never returns the full key. */
  hint: string | null;
}

export type KeysStatus = Record<Provider, KeyStatus>;

export const PROVIDERS: Provider[] = ['openai', 'anthropic'];

/** Saving rewrites backend/.env; a backend started with --reload-include .env restarts. */
const RESTART_POLL_MS = 1000;
const RESTART_POLLS = 8;

/** Which API keys the backend has. Keys themselves only travel browser → backend, once. */
@Injectable({ providedIn: 'root' })
export class KeysStore {
  private readonly http = inject(HttpClient);

  /** null until the first successful load (e.g. while the backend is offline). */
  readonly status = signal<KeysStatus | null>(null);

  readonly missing = computed(() => {
    const status = this.status();
    return status ? PROVIDERS.filter((p) => !status[p].configured) : [];
  });
  // Unknown counts as ready, so nothing is blocked before the backend has answered.
  readonly openaiReady = computed(() => this.status()?.openai.configured ?? true);
  readonly searchReady = computed(() => this.missing().length === 0);

  async load(): Promise<void> {
    try {
      this.status.set(await firstValueFrom(this.http.get<KeysStatus>(`${API_BASE_URL}/settings/keys`)));
    } catch {
      // Backend offline: the sidebar already says so.
    }
  }

  /** Check the key with its provider (free) and save it; throws with the backend's message on failure. */
  async save(provider: Provider, key: string): Promise<void> {
    try {
      this.status.set(
        await firstValueFrom(this.http.put<KeysStatus>(`${API_BASE_URL}/settings/keys/${provider}`, { key })),
      );
    } catch (error) {
      // The answer can be lost when the backend restarts right after writing .env.
      if (error instanceof HttpErrorResponse && error.status === 0 && (await this.cameBackWith(provider))) {
        return;
      }
      throw error;
    }
  }

  private async cameBackWith(provider: Provider): Promise<boolean> {
    for (let i = 0; i < RESTART_POLLS; i++) {
      await new Promise((resolve) => setTimeout(resolve, RESTART_POLL_MS));
      await this.load();
      if (this.status()?.[provider].configured) {
        return true;
      }
    }
    return false;
  }
}
