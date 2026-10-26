import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, input, linkedSignal, signal } from '@angular/core';

import { DocumentsStore } from '../core/documents.store';
import { AgentMatch } from '../core/models';
import { FileBadge } from '../ui/file-badge';
import { Icon } from '../ui/icon';

@Component({
  selector: 'app-match-card',
  imports: [DecimalPipe, FileBadge, Icon],
  host: { class: 'block' },
  template: `
    <article class="overflow-hidden rounded-xl border border-line bg-elevated">
      <button
        type="button"
        class="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-raised"
        [attr.aria-expanded]="open()"
        (click)="open.set(!open())"
      >
        <span class="grid size-6 shrink-0 place-items-center rounded-full bg-accent/15 text-xs font-semibold text-accent">
          {{ rank() }}
        </span>
        <app-file-badge [type]="match().file_type" />
        <span class="min-w-0 flex-1 truncate text-sm font-medium text-ink">{{ match().filename }}</span>
        @if (match().similarity !== null) {
          <span
            class="rounded-md border border-line px-1.5 py-0.5 text-[11px] tabular-nums text-ink-muted"
            title="Similarity of the best-matching passage (1 = identical meaning). A relative ranking signal, not a confidence score."
          >
            sim {{ match().similarity | number: '1.2-2' }}
          </span>
        }
        <app-icon name="chevron-down" class="text-ink-faint transition-transform" [class.rotate-180]="open()" />
      </button>

      @if (open()) {
        <div class="space-y-3 border-t border-line px-3 py-3">
          @if (match().reason) {
            <p class="text-sm leading-relaxed text-ink/90">{{ match().reason }}</p>
          }

          @for (excerpt of visibleExcerpts(); track $index) {
            <figure class="rounded-lg border border-line bg-canvas/60 p-3">
              <blockquote class="text-sm leading-relaxed text-ink-muted">“{{ excerpt.text }}”</blockquote>
              <figcaption class="mt-2 flex items-center gap-1.5 text-xs text-ink-faint">
                <app-icon name="file-text" [size]="12" />
                {{ excerpt.location }}
              </figcaption>
            </figure>
          }
          @if (hiddenCount() > 0) {
            <button type="button" class="text-xs text-accent hover:underline" (click)="showAll.set(true)">
              Show {{ hiddenCount() }} more excerpt{{ hiddenCount() === 1 ? '' : 's' }}
            </button>
          }

          <div class="flex items-center gap-2">
            <a
              class="inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-sm font-medium text-ink hover:bg-raised"
              target="_blank"
              rel="noopener"
              [href]="docs.openUrl(match().file_id)"
            >
              <app-icon name="external-link" [size]="14" />
              Open file
            </a>
            @if (match().excerpts.length) {
              <button
                type="button"
                class="grid size-8 place-items-center rounded-lg border border-line text-ink-muted hover:bg-raised hover:text-ink"
                [attr.aria-label]="copied() ? 'Copied' : 'Copy excerpt'"
                [title]="copied() ? 'Copied' : 'Copy excerpt'"
                (click)="copyExcerpt()"
              >
                <app-icon [name]="copied() ? 'check' : 'copy'" [size]="14" />
              </button>
            }
            <span class="ml-auto font-mono text-[11px] text-ink-faint">#{{ match().file_id.slice(0, 8) }}</span>
          </div>
        </div>
      }
    </article>
  `,
})
export class MatchCard {
  protected readonly docs = inject(DocumentsStore);

  readonly match = input.required<AgentMatch>();
  readonly rank = input.required<number>();
  readonly initiallyOpen = input(false);

  protected readonly open = linkedSignal(() => this.initiallyOpen());
  protected readonly showAll = signal(false);
  protected readonly copied = signal(false);

  protected readonly visibleExcerpts = computed(() =>
    this.showAll() ? this.match().excerpts : this.match().excerpts.slice(0, 1),
  );
  protected readonly hiddenCount = computed(
    () => this.match().excerpts.length - this.visibleExcerpts().length,
  );

  protected async copyExcerpt(): Promise<void> {
    const [first] = this.match().excerpts;
    if (!first) {
      return;
    }
    try {
      await navigator.clipboard.writeText(`${first.text}\n— ${this.match().filename}, ${first.location}`);
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    } catch {
      // Clipboard access can be blocked; copying is a convenience, so fail quietly.
    }
  }
}
