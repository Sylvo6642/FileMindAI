import { Component, computed, input } from '@angular/core';

import { FileType } from '../core/models';

const TONES: Record<FileType, string> = {
  pdf: 'bg-rose-500/15 text-rose-300',
  docx: 'bg-sky-500/15 text-sky-300',
  txt: 'bg-zinc-500/20 text-zinc-300',
};

@Component({
  selector: 'app-file-badge',
  host: { class: 'inline-flex shrink-0' },
  template: `
    <span
      class="inline-grid h-5 min-w-9 place-items-center rounded px-1 text-[10px] font-semibold uppercase tracking-wide"
      [class]="tone()"
      >{{ type() }}</span
    >
  `,
})
export class FileBadge {
  readonly type = input.required<FileType>();
  protected readonly tone = computed(() => TONES[this.type()] ?? TONES.txt);
}
