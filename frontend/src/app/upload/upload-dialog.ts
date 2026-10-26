import { DecimalPipe } from '@angular/common';
import { Component, ElementRef, computed, inject, output, signal, viewChild } from '@angular/core';

import { describeHttpError } from '../core/api-error';
import { DocumentsStore, SkippedFile, screenFiles } from '../core/documents.store';
import { MAX_SCANNED_FILES, PickedFile, filesFromDrop, filesFromInput } from '../core/file-picker';
import { KeysStore } from '../core/keys.store';
import { FileType, UploadEstimate } from '../core/models';
import { FileBadge } from '../ui/file-badge';
import { Icon } from '../ui/icon';

/** Estimates are local and quick; a few at a time keeps a big folder moving without flooding the backend. */
const PARALLEL_ESTIMATES = 3;

/** A picked file in the review step, before anything is sent to the embedding model. */
interface ReviewRow {
  id: number;
  picked: PickedFile;
  estimate?: UploadEstimate;
  error?: string;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  const mb = bytes / (1024 * 1024);
  return mb < 1024 ? `${mb.toFixed(1)} MB` : `${(mb / 1024).toFixed(1)} GB`;
}

/** Embedding costs are tiny, so show significant digits instead of rounding to $0.00. */
export function formatCost(usd: number): string {
  if (usd === 0) {
    return '$0.00';
  }
  return usd >= 0.01 ? `$${usd.toFixed(2)}` : `$${usd.toPrecision(2)}`;
}

function splitPath(path: string): { name: string; folder: string; type: FileType } {
  const slash = path.lastIndexOf('/');
  const name = path.slice(slash + 1);
  const ext = name.slice(name.lastIndexOf('.') + 1).toLowerCase();
  return {
    name,
    folder: slash > 0 ? path.slice(0, slash) : '',
    type: (['pdf', 'docx'].includes(ext) ? ext : 'txt') as FileType,
  };
}

function uploadable(row: ReviewRow): boolean {
  return !!row.estimate && !row.estimate.duplicate_of;
}

@Component({
  selector: 'app-upload-dialog',
  imports: [Icon, FileBadge, DecimalPipe],
  templateUrl: './upload-dialog.html',
})
export class UploadDialog {
  protected readonly docs = inject(DocumentsStore);
  protected readonly keys = inject(KeysStore);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  /** Estimating works without a key (it's local); embedding needs the OpenAI key. */
  readonly addKey = output<void>();

  protected readonly dragOver = signal(false);
  protected readonly scanning = signal(false);
  protected readonly truncated = signal(false);
  protected readonly showSkipped = signal(false);
  protected readonly formatSize = formatSize;
  protected readonly formatCost = formatCost;
  protected readonly maxScanned = MAX_SCANNED_FILES;

  // Review step: files are estimated (locally, free) and wait for the user's go-ahead.
  protected readonly review = signal<ReviewRow[]>([]);
  protected readonly reviewSkipped = signal<SkippedFile[]>([]);
  private nextRowId = 1;
  /** Bumped on cancel/confirm so estimates still in flight are dropped. */
  private reviewRun = 0;

  protected readonly reviewing = computed(() => this.review().length > 0 || this.reviewSkipped().length > 0);

  protected readonly reviewRows = computed(() => this.review().map((row) => ({ row, ...splitPath(row.picked.path) })));

  protected readonly reviewTotals = computed(() => {
    const rows = this.review();
    const ready = rows.filter(uploadable);
    return {
      estimated: rows.filter((r) => r.estimate || r.error).length,
      total: rows.length,
      files: ready.length,
      tokens: ready.reduce((sum, r) => sum + r.estimate!.token_count, 0),
      cost: ready.reduce((sum, r) => sum + r.estimate!.estimated_cost_usd, 0),
      model: ready[0]?.estimate?.embedding_model ?? null,
      excluded: rows.length - ready.length,
    };
  });

  protected readonly estimating = computed(() => {
    const totals = this.reviewTotals();
    return totals.estimated < totals.total;
  });

  /** Upload rows joined with the live library, so a later reindex or failure shows up here too. */
  protected readonly rows = computed(() => {
    const byId = new Map(this.docs.documents().map((d) => [d.file_id, d]));
    return this.docs.uploads().map((item) => ({
      item,
      ...splitPath(item.path),
      doc: item.fileId ? byId.get(item.fileId) : undefined,
    }));
  });

  /** Embedding dominates the time, so sending the bytes counts as half of a file. */
  protected readonly overall = computed(() => {
    const items = this.docs.uploads();
    if (!items.length) {
      return 0;
    }
    const units = items.reduce((sum, item) => {
      switch (item.state) {
        case 'done':
        case 'error':
          return sum + 1;
        case 'indexing':
          return sum + 0.5;
        case 'uploading':
          return sum + item.progress * 0.5;
        default:
          return sum;
      }
    }, 0);
    return units / items.length;
  });

  protected readonly skippedSummary = computed(() => summarize(this.docs.skipped()));
  protected readonly reviewSkippedSummary = computed(() => summarize(this.reviewSkipped()));

  open(): void {
    const el = this.dialog().nativeElement;
    if (el.open) {
      return;
    }
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

  /** Closing the dialog abandons an unconfirmed review: nothing was uploaded. */
  protected onClosed(): void {
    this.dragOver.set(false);
    this.cancelReview();
  }

  /** Clicks on the dimmed backdrop land on the <dialog> itself; the content wrapper catches the rest. */
  protected onDialogClick(event: MouseEvent): void {
    if (event.target === this.dialog().nativeElement) {
      this.close();
    }
  }

  protected onDragOver(event: DragEvent): void {
    if (event.dataTransfer?.types.includes('Files')) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
      this.dragOver.set(true);
    }
  }

  protected onDragLeave(event: DragEvent): void {
    const to = event.relatedTarget as Node | null;
    if (!to || !this.dialog().nativeElement.contains(to)) {
      this.dragOver.set(false);
    }
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation(); // the app also listens for drops
    this.dropFiles(event.dataTransfer);
  }

  /** Handle a drop, from this dialog or anywhere in the app. */
  dropFiles(data: DataTransfer | null): void {
    this.open();
    this.dragOver.set(false);
    if (!data) {
      return;
    }
    // filesFromDrop reads the drop synchronously before its first await, as it must.
    const reading = filesFromDrop(data);
    this.scanning.set(true);
    void reading.then((files) => this.startReview(files)).finally(() => this.scanning.set(false));
  }

  protected onPicked(input: HTMLInputElement): void {
    const files = filesFromInput(input);
    input.value = ''; // allow picking the same files again later
    void this.startReview(files);
  }

  /** Take one file out of the review; an estimate still in flight for it is simply ignored. */
  protected removeFromReview(id: number): void {
    this.review.update((list) => list.filter((row) => row.id !== id));
  }

  protected cancelReview(): void {
    this.reviewRun++;
    this.review.set([]);
    this.reviewSkipped.set([]);
  }

  /** The only place files are handed to the upload queue, and so to the embedding model. */
  protected confirmReview(): void {
    const rows = this.review();
    const skipped: SkippedFile[] = [...this.reviewSkipped()];
    for (const row of rows) {
      if (row.error) {
        skipped.push({ path: row.picked.path, reason: row.error });
      } else if (row.estimate?.duplicate_of) {
        skipped.push({ path: row.picked.path, reason: `Already in the library as ${row.estimate.duplicate_of}` });
      }
    }
    const accepted = rows.filter(uploadable).map((row) => row.picked);
    this.cancelReview();
    void this.docs.queue(accepted, skipped);
  }

  /** Add files to the review (picking more while reviewing extends it) and estimate them. */
  private async startReview(files: PickedFile[]): Promise<void> {
    if (!files.length) {
      return;
    }
    this.truncated.set(files.length >= MAX_SCANNED_FILES);
    const { accepted, skipped } = screenFiles(files);
    const rows = accepted.map((picked): ReviewRow => ({ id: this.nextRowId++, picked }));
    this.review.update((list) => [...list, ...rows]);
    this.reviewSkipped.update((list) => [...list, ...skipped]);

    const run = this.reviewRun;
    const pending = [...rows];
    const worker = async () => {
      for (let row = pending.shift(); row; row = pending.shift()) {
        let changes: Partial<ReviewRow>;
        try {
          changes = { estimate: await this.docs.estimate(row.picked.file) };
        } catch (error) {
          changes = { error: describeHttpError(error) };
        }
        if (run !== this.reviewRun) {
          return; // cancelled or confirmed meanwhile
        }
        const id = row.id;
        this.review.update((list) => list.map((r) => (r.id === id ? { ...r, ...changes } : r)));
      }
    };
    await Promise.all(Array.from({ length: Math.min(PARALLEL_ESTIMATES, rows.length) }, worker));
  }
}

function summarize(skipped: SkippedFile[]): string {
  const counts = new Map<string, number>();
  for (const { reason } of skipped) {
    counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }
  // "Temporary Office file" → "temporary Office file": only the first letter, so "MB" and "Office" survive.
  return Array.from(counts, ([reason, n]) => `${n} ${reason[0].toLowerCase()}${reason.slice(1)}`).join(', ');
}
