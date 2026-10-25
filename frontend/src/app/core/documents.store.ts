import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api.config';
import { describeHttpError } from './api-error';
import { DocumentList, DocumentRecord } from './models';

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt'];
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const REFRESH_MS = 3000;

export interface UploadItem {
  id: number;
  filename: string;
  state: 'uploading' | 'error';
  error?: string;
}

/** The document library: list, upload, reindex and delete. */
@Injectable({ providedIn: 'root' })
export class DocumentsStore {
  private readonly http = inject(HttpClient);
  private nextUploadId = 1;

  readonly documents = signal<DocumentRecord[]>([]);
  readonly uploads = signal<UploadItem[]>([]);
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

  /** Upload one file at a time: each upload embeds the file, so they are not instant. */
  async uploadFiles(files: File[]): Promise<void> {
    for (const file of files) {
      const id = this.nextUploadId++;
      const problem = this.checkLocally(file);
      if (problem) {
        this.uploads.update((items) => [...items, { id, filename: file.name, state: 'error', error: problem }]);
        continue;
      }

      this.uploads.update((items) => [...items, { id, filename: file.name, state: 'uploading' }]);
      const form = new FormData();
      form.append('file', file, file.name);
      try {
        const record = await firstValueFrom(
          this.http.post<DocumentRecord>(`${API_BASE_URL}/documents/upload`, form),
        );
        // A refresh during the upload may already list this document.
        this.documents.update((docs) => [record, ...docs.filter((d) => d.file_id !== record.file_id)]);
        this.dismissUpload(id);
      } catch (error) {
        this.uploads.update((items) =>
          items.map((item) =>
            item.id === id ? { ...item, state: 'error', error: describeHttpError(error) } : item,
          ),
        );
      }
    }
  }

  dismissUpload(id: number): void {
    this.uploads.update((items) => items.filter((item) => item.id !== id));
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

  // Mirrors the backend's rules so obvious mistakes fail instantly.
  private checkLocally(file: File): string | null {
    const name = file.name.toLowerCase();
    if (!ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      return 'Unsupported file type. Allowed: PDF, DOCX, TXT.';
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      return 'File exceeds the 20 MB limit.';
    }
    if (file.size === 0) {
      return 'The file is empty.';
    }
    return null;
  }
}
