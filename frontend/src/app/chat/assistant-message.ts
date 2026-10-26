import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, input, output, signal } from '@angular/core';

import { ChatTurn } from '../core/chat.store';
import { ActivityStep } from '../core/models';
import { Icon } from '../ui/icon';
import { MatchCard } from './match-card';

@Component({
  selector: 'app-assistant-message',
  imports: [DatePipe, DecimalPipe, Icon, MatchCard],
  host: { class: 'block' },
  template: `
    <div class="flex gap-3">
      <img src="logo.png" alt="" class="size-8 shrink-0" width="32" height="32" />

      <div class="min-w-0 flex-1 rounded-2xl border border-line bg-panel p-4">
        <div class="flex items-baseline gap-2">
          <span class="text-sm font-semibold text-ink">FileMind</span>
          <span class="text-xs text-ink-faint">{{ turn().askedAt | date: 'shortTime' }}</span>
        </div>

        @switch (turn().status) {
          @case ('loading') {
            <div class="mt-3 flex items-center gap-2 text-sm text-ink-muted" role="status">
              <app-icon name="loader" class="animate-spin text-accent" />
              Searching your documents…
            </div>
          }

          @case ('error') {
            <div
              class="mt-3 flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200"
              role="alert"
            >
              <app-icon name="alert" class="mt-0.5" />
              <span class="flex-1">{{ turn().error }}</span>
              <button type="button" class="shrink-0 text-rose-100 underline hover:no-underline" (click)="retry.emit(turn().id)">
                Retry
              </button>
            </div>
          }

          @case ('done') {
            @if (turn().response; as result) {
              @if (result.activity.length) {
                <ol class="mt-3 space-y-1.5 border-l border-line pl-3" aria-label="Tool activity">
                  @for (step of result.activity; track $index) {
                    <li
                      class="flex items-start gap-2 text-xs"
                      [class.text-ink-muted]="!step.is_error"
                      [class.text-rose-300]="step.is_error"
                    >
                      <app-icon [name]="step.tool === 'inspect_file' ? 'eye' : 'search'" [size]="13" class="mt-px" />
                      <span>{{ describe(step) }}</span>
                    </li>
                  }
                </ol>
              }

              <p class="mt-3 whitespace-pre-line text-sm leading-relaxed text-ink">{{ result.answer }}</p>

              @if (result.matches.length) {
                <button
                  type="button"
                  class="mt-4 flex items-center gap-2 text-sm text-ink-muted hover:text-ink"
                  [attr.aria-expanded]="matchesOpen()"
                  (click)="matchesOpen.set(!matchesOpen())"
                >
                  <app-icon name="file-text" />
                  Matches ({{ result.matches.length }})
                  <app-icon name="chevron-down" class="transition-transform" [class.rotate-180]="matchesOpen()" />
                </button>
                @if (matchesOpen()) {
                  <div class="mt-3 space-y-2">
                    @for (match of result.matches; track match.file_id; let i = $index) {
                      <app-match-card [match]="match" [rank]="i + 1" [initiallyOpen]="i === 0" />
                    }
                  </div>
                }
              }

              <p class="mt-4 text-[11px] text-ink-faint">
                {{ result.model ?? 'No model call' }} · {{ result.tool_rounds }} tool
                round{{ result.tool_rounds === 1 ? '' : 's' }} ·
                {{ result.usage.input_tokens | number }} in / {{ result.usage.output_tokens | number }} out tokens
              </p>
            }
          }
        }
      </div>
    </div>
  `,
})
export class AssistantMessage {
  readonly turn = input.required<ChatTurn>();
  readonly retry = output<number>();

  protected readonly matchesOpen = signal(true);

  protected describe(step: ActivityStep): string {
    if (step.tool === 'search_files' && !step.is_error && typeof step.input['query'] === 'string') {
      return `Searched “${step.input['query']}” · ${step.summary}`;
    }
    return step.summary;
  }
}
