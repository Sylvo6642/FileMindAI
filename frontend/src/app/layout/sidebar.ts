import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, output, signal } from '@angular/core';

import { DocumentsStore } from '../core/documents.store';
import { HealthResponse, HealthService } from '../core/health.service';
import { HistoryStore } from '../core/history.store';
import { KeysStore } from '../core/keys.store';
import { DocumentRecord } from '../core/models';
import { FileBadge } from '../ui/file-badge';
import { Icon } from '../ui/icon';

@Component({
  selector: 'app-sidebar',
  imports: [Icon, FileBadge, DecimalPipe],
  templateUrl: './sidebar.html',
  host: {
    class: 'flex h-full w-72 flex-col border-r border-line bg-panel',
    '(document:click)': 'onDocumentClick($event)',
    '(document:keydown.escape)': 'closeMenu()',
    // Coming back to the tab (e.g. after restarting the backend) refreshes status.
    '(window:focus)': 'refresh()',
  },
})
export class Sidebar {
  protected readonly docs = inject(DocumentsStore);
  protected readonly history = inject(HistoryStore);
  private readonly keys = inject(KeysStore);
  private readonly healthService = inject(HealthService);

  readonly newSearch = output<void>();
  readonly upload = output<void>();
  readonly apiKeys = output<void>();
  readonly searchSelected = output<string>();

  protected readonly filter = signal('');
  protected readonly docsOpen = signal(true);
  protected readonly searchesOpen = signal(true);
  protected readonly menuFor = signal<string | null>(null);
  protected readonly confirmDelete = signal<string | null>(null);
  protected readonly confirmClear = signal(false);
  protected readonly health = signal<HealthResponse | null>(null);
  protected readonly healthState = signal<'checking' | 'ok' | 'offline'>('checking');

  protected readonly filteredDocs = computed(() => {
    const term = this.filter().trim().toLowerCase();
    const docs = this.docs.documents();
    return term ? docs.filter((d) => d.filename.toLowerCase().includes(term)) : docs;
  });

  protected readonly missingKeys = computed(() => {
    const names = this.keys.missing().map((p) => (p === 'openai' ? 'OpenAI' : 'Anthropic'));
    if (!names.length) {
      return null;
    }
    return names.length === 1 ? `${names[0]} API key missing` : `${names.join(' and ')} API keys missing`;
  });

  protected readonly totalChunks = computed(() =>
    this.docs.documents().reduce((sum, d) => sum + (d.status === 'indexed' ? d.chunk_count : 0), 0),
  );

  constructor() {
    this.checkHealth();
  }

  protected checkHealth(): void {
    this.healthState.set('checking');
    this.healthService.getHealth().subscribe({
      next: (health) => {
        this.health.set(health);
        this.healthState.set('ok');
      },
      error: () => this.healthState.set('offline'),
    });
  }

  protected refresh(): void {
    this.checkHealth();
    void this.docs.load();
    void this.keys.load();
    void this.history.load();
  }

  /** Two-step, like deleting a document: the first click arms it for a few seconds. */
  protected clearHistory(): void {
    if (!this.confirmClear()) {
      this.confirmClear.set(true);
      setTimeout(() => this.confirmClear.set(false), 4000);
      return;
    }
    this.confirmClear.set(false);
    void this.history.clear().catch(() => this.history.load());
  }

  protected toggleMenu(fileId: string, event: Event): void {
    event.stopPropagation();
    this.confirmDelete.set(null);
    this.menuFor.update((current) => (current === fileId ? null : fileId));
  }

  protected closeMenu(): void {
    this.menuFor.set(null);
    this.confirmDelete.set(null);
  }

  protected onDocumentClick(event: Event): void {
    if (!(event.target as Element | null)?.closest('[data-doc-menu]')) {
      this.closeMenu();
    }
  }

  protected reindex(doc: DocumentRecord): void {
    this.closeMenu();
    void this.docs.reindex(doc);
  }

  protected delete(doc: DocumentRecord): void {
    // Two-step delete: the first click arms it, the second confirms.
    if (this.confirmDelete() !== doc.file_id) {
      this.confirmDelete.set(doc.file_id);
      return;
    }
    this.closeMenu();
    void this.docs.remove(doc);
  }

  protected statusTitle(doc: DocumentRecord): string {
    if (doc.status === 'indexed') {
      return `Indexed · ${doc.chunk_count} chunk${doc.chunk_count === 1 ? '' : 's'}`;
    }
    if (doc.status === 'failed') {
      return doc.error_message ?? 'Indexing failed';
    }
    return 'Indexing…';
  }
}
