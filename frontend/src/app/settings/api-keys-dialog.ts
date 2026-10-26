import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';

import { describeHttpError } from '../core/api-error';
import { KeysStore, PROVIDERS, Provider } from '../core/keys.store';
import { Icon } from '../ui/icon';

interface ProviderInfo {
  name: string;
  purpose: string;
  placeholder: string;
  keysUrl: string;
}

const INFO: Record<Provider, ProviderInfo> = {
  openai: {
    name: 'OpenAI',
    purpose: 'Turns your documents and questions into embeddings. Needed to upload and to search.',
    placeholder: 'sk-…',
    keysUrl: 'https://platform.openai.com/api-keys',
  },
  anthropic: {
    name: 'Anthropic',
    purpose: 'Runs the search assistant (Claude) that reads the matches and explains them. Needed to search.',
    placeholder: 'sk-ant-…',
    keysUrl: 'https://console.anthropic.com/settings/keys',
  },
};

interface ProviderState {
  draft: string;
  reveal: boolean;
  saving: boolean;
  error: string | null;
  saved: boolean;
}

const EMPTY: ProviderState = { draft: '', reveal: false, saving: false, error: null, saved: false };

@Component({
  selector: 'app-api-keys-dialog',
  imports: [Icon],
  templateUrl: './api-keys-dialog.html',
})
export class ApiKeysDialog {
  protected readonly keys = inject(KeysStore);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  protected readonly providers = PROVIDERS;
  protected readonly info = INFO;
  protected readonly state = signal<Record<Provider, ProviderState>>({ openai: EMPTY, anthropic: EMPTY });
  protected readonly anyMissing = computed(() => this.keys.missing().length > 0);

  open(): void {
    const el = this.dialog().nativeElement;
    if (el.open) {
      return;
    }
    void this.keys.load();
    if (typeof el.showModal === 'function') {
      el.showModal();
    } else {
      el.setAttribute('open', '');
    }
  }

  protected close(): void {
    const el = this.dialog().nativeElement;
    if (typeof el.close === 'function') {
      el.close();
    } else {
      el.removeAttribute('open');
      this.onClosed();
    }
  }

  /** Forget anything typed: a key should not linger in the page after the dialog closes. */
  protected onClosed(): void {
    this.state.set({ openai: EMPTY, anthropic: EMPTY });
  }

  protected onDialogClick(event: MouseEvent): void {
    if (event.target === this.dialog().nativeElement) {
      this.close();
    }
  }

  protected setDraft(provider: Provider, value: string): void {
    this.patch(provider, { draft: value, error: null, saved: false });
  }

  protected toggleReveal(provider: Provider): void {
    this.patch(provider, { reveal: !this.state()[provider].reveal });
  }

  protected async save(provider: Provider, event: Event): Promise<void> {
    event.preventDefault();
    const key = this.state()[provider].draft.trim();
    if (!key || this.state()[provider].saving) {
      return;
    }
    this.patch(provider, { saving: true, error: null, saved: false });
    try {
      await this.keys.save(provider, key);
      this.patch(provider, { ...EMPTY, saved: true });
    } catch (error) {
      this.patch(provider, { saving: false, error: describeHttpError(error) });
    }
  }

  private patch(provider: Provider, changes: Partial<ProviderState>): void {
    this.state.update((all) => ({ ...all, [provider]: { ...all[provider], ...changes } }));
  }
}
