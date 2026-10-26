import { HttpClient, HttpErrorResponse, HttpEventType } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api.config';
import { describeHttpError } from './api-error';
import { PickedFile } from './file-picker';
import { DocumentList, DocumentRecord, UploadEstimate } from './models';

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt'];
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const REFRESH_MS = 3000;
/** Each upload is embedded before the backend answers, so a little parallelism hides the wait. */
const PARALLEL_UPLOADS = 2;

export type UploadState = 'queued' | 'uploading' | 'indexing' | 'done' | 'error';

export interface UploadItem {
  id: number;
  /** Path inside a picked folder, or just the filename. */
  path: string;
  size: number;
  state: UploadState;
  /** Share of the bytes sent, 0–1. */
  progress: number;
  error?: string;
  /** Network and server failures can be retried; rejections (duplicate, invalid file) cannot. */
  retryable?: boolean;
  /** The stored document, once the backend has answered. */
  fileId?: string;
}

export interface SkippedFile {
  path: string;
  reason: string;
}

/** Split picked files into ones worth sending and ones the backend would reject anyway. */
export function screenFiles(files: PickedFile[]): { accepted: PickedFile[]; skipped: SkippedFile[] } {
  const accepted: PickedFile[] = [];
  const skipped: SkippedFile[] = [];
  for (const picked of files) {
    const reason = rejectReason(picked.file);
    if (reason) {
      skipped.push({ path: picked.path, reason });
    } else {
      accepted.push(picked);
    }
  }
  return { accepted, skipped };
}

// Mirrors the backend's rules so obvious mistakes fail instantly.
function rejectReason(file: File): string | null {
  const name = file.name.toLowerCase();
  if (name.startsWith('~$')) {
    return 'Temporary Office file';
  }
  if (!ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return 'Unsupported file type';
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return 'Larger than 20 MB';
  }
  if (file.size === 0) {
    return 'Empty file';
  }
  return null;
}

/** The document library: list, upload, reindex and delete. */
@Injectable({ providedIn: 'root' })
export class DocumentsStore {
  private readonly http = inject(HttpClient);
  private nextUploadId = 1;
  private running = 0;
  /** Files waiting to be sent (or retried), kept out of the signal state. */
  private readonly pendingFiles = new Map<number, File>();

  readonly documents = signal<DocumentRecord[]>([]);
  readonly uploads = signal<UploadItem[]>([]);
  readonly skipped = signal<SkippedFile[]>([]);
  readonly uploadSummary = computed(() => {
    const items = this.uploads();
    const done = items.filter((i) => i.state === 'done').length;
    const failed = items.filter((i) => i.state === 'error').length;
    return { total: items.length, done, failed, active: items.length - done - failed };
  });
  readonly loading = signal(false);
  /** True once the list has been fetched at least once. */
  readonly loaded = signal(false);
  readonly notice = signal<string | null>(null);

  readonly indexedCount = computed(
    () => this.documents().filter((d) => d.status === 'indexed').length,
  );
  /** Searching an empty library is pointless; before the first load we can't tell, so allow it. */
  readonly canSearch = computed(() => !this.loaded() || this.indexedCount() > 0);

  private refreshTimer: ReturnType<typeof setTimeout> | null = null;

  openUrl(fileId: string): string {
    return `${API_BASE_URL}/documents/${fileId}/open`;
  }

  async load(): Promise<void> {
    this.loading.set(true);
    try {
      const list = await firstValueFrom(this.http.get<DocumentList>(`${API_BASE_URL}/documents`));
      this.documents.set(list.documents);
      this.loaded.set(true);
      this.scheduleRefresh();
    } catch (error) {
      this.notice.set(describeHttpError(error));
    } finally {
      this.loading.set(false);
    }
  }

  /** Tokens and cost of uploading a file. The backend only reads it: nothing is saved or embedded. */
  estimate(file: File): Promise<UploadEstimate> {
    const form = new FormData();
    form.append('file', file, file.name);
    return firstValueFrom(this.http.post<UploadEstimate>(`${API_BASE_URL}/documents/estimate`, form));
  }

  /** Screen and upload files; resolves when the queue is empty. */
  add(files: PickedFile[]): Promise<void> {
    const { accepted, skipped } = screenFiles(files);
    return this.queue(accepted, skipped);
  }

  /** Queue already-screened files and start sending them. */
  queue(accepted: PickedFile[], skipped: SkippedFile[] = []): Promise<void> {
    this.skipped.update((list) => [...list, ...skipped]);
    const items = accepted.map(({ file, path }): UploadItem => {
      const id = this.nextUploadId++;
      this.pendingFiles.set(id, file);
      return { id, path, size: file.size, state: 'queued', progress: 0 };
    });
    this.uploads.update((list) => [...list, ...items]);
    return this.pump();
  }

  retryUpload(id: number): Promise<void> {
    this.patch(id, { state: 'queued', progress: 0, error: undefined, retryable: undefined });
    return this.pump();
  }

  dismissUpload(id: number): void {
    this.pendingFiles.delete(id);
    this.uploads.update((items) => items.filter((item) => item.id !== id));
  }

  /** Forget finished and failed uploads and the skipped list; queued and running ones stay. */
  clearFinished(): void {
    for (const item of this.uploads()) {
      if (item.state === 'done' || item.state === 'error') {
        this.pendingFiles.delete(item.id);
      }
    }
    this.uploads.update((items) => items.filter((i) => i.state !== 'done' && i.state !== 'error'));
    this.skipped.set([]);
  }

  async reindex(doc: DocumentRecord): Promise<void> {
    this.replace({ ...doc, status: 'processing', error_message: null });
    try {
      const record = await firstValueFrom(
        this.http.post<DocumentRecord>(`${API_BASE_URL}/documents/${doc.file_id}/reindex`, {}),
      );
      this.replace(record);
    } catch (error) {
      this.replace(doc);
      this.notice.set(describeHttpError(error));
    }
  }

  async remove(doc: DocumentRecord): Promise<void> {
    try {
      await firstValueFrom(this.http.delete(`${API_BASE_URL}/documents/${doc.file_id}`));
      this.documents.update((docs) => docs.filter((d) => d.file_id !== doc.file_id));
    } catch (error) {
      this.notice.set(describeHttpError(error));
    }
  }

  // Another tab, or a refresh mid-upload, can show documents still being indexed.
  // Check back until they settle, so the sidebar never needs a manual reload.
  private scheduleRefresh(): void {
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
    if (this.documents().some((d) => d.status === 'pending' || d.status === 'processing')) {
      this.refreshTimer = setTimeout(() => void this.load(), REFRESH_MS);
    }
  }

  private replace(record: DocumentRecord): void {
    this.documents.update((docs) => docs.map((d) => (d.file_id === record.file_id ? record : d)));
  }

  /** Start workers up to the parallel limit; resolves when they run out of queued files. */
  private pump(): Promise<void> {
    const workers: Promise<void>[] = [];
    while (this.running < PARALLEL_UPLOADS && this.uploads().some((i) => i.state === 'queued')) {
      workers.push(this.work());
    }
    return Promise.all(workers).then(() => undefined);
  }

  private async work(): Promise<void> {
    this.running++;
    try {
      for (let item = this.takeNext(); item; item = this.takeNext()) {
        await this.send(item);
      }
    } finally {
      this.running--;
    }
  }

  // Marks the item synchronously so two workers never take the same file.
  private takeNext(): UploadItem | undefined {
    const item = this.uploads().find((i) => i.state === 'queued');
    if (item) {
      this.patch(item.id, { state: 'uploading', progress: 0 });
    }
    return item;
  }

  private send(item: UploadItem): Promise<void> {
    const file = this.pendingFiles.get(item.id)!;
    const form = new FormData();
    form.append('file', file, file.name);
    return new Promise((resolve) => {
      this.http
        .post<DocumentRecord>(`${API_BASE_URL}/documents/upload`, form, { reportProgress: true, observe: 'events' })
        .subscribe({
          next: (event) => {
            if (event.type === HttpEventType.UploadProgress) {
              const progress = event.total ? event.loaded / event.total : 0;
              // Once every byte is sent the backend is extracting and embedding.
              this.patch(item.id, progress >= 1 ? { state: 'indexing', progress: 1 } : { progress });
            } else if (event.type === HttpEventType.Response && event.body) {
              const record = event.body;
              this.pendingFiles.delete(item.id);
              this.patch(item.id, { state: 'done', progress: 1, fileId: record.file_id });
              // A refresh during the upload may already list this document.
              this.documents.update((docs) => [record, ...docs.filter((d) => d.file_id !== record.file_id)]);
            }
          },
          error: (error: unknown) => {
            const status = error instanceof HttpErrorResponse ? error.status : 0;
            this.patch(item.id, {
              state: 'error',
              error: describeHttpError(error),
              retryable: status === 0 || status >= 500,
            });
            resolve();
          },
          complete: () => resolve(),
        });
    });
  }

  private patch(id: number, changes: Partial<UploadItem>): void {
    this.uploads.update((items) => items.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }
}
