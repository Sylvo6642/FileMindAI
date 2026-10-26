import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { API_BASE_URL } from './api.config';
import { DocumentsStore } from './documents.store';
import { PickedFile } from './file-picker';
import { DocumentRecord } from './models';

export function makeDoc(overrides: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    file_id: 'a1b2c3d4-0000-0000-0000-000000000001',
    filename: 'agreement_001.pdf',
    file_type: 'pdf',
    size_bytes: 5295,
    sha256: 'x',
    status: 'indexed',
    page_count: 4,
    char_count: 3900,
    chunk_count: 2,
    warnings: [],
    error_message: null,
    created_at: '2026-10-25T10:00:00+00:00',
    updated_at: '2026-10-25T10:00:00+00:00',
    ...overrides,
  };
}

/** Let pending promise continuations run (the store awaits HTTP calls). */
const settle = () => new Promise((resolve) => setTimeout(resolve));

const UPLOAD_URL = `${API_BASE_URL}/documents/upload`;

/** Small text files at the given paths, as a file or folder picker would return them. */
function picked(...paths: string[]): PickedFile[] {
  return paths.map((path) => ({ file: new File(['hello'], path.split('/').pop()!), path }));
}

describe('DocumentsStore', () => {
  let store: DocumentsStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    store = TestBed.inject(DocumentsStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('loads the document list', async () => {
    const loading = store.load();
    http.expectOne(`${API_BASE_URL}/documents`).flush({ count: 1, documents: [makeDoc()] });
    await loading;

    expect(store.documents().map((d) => d.filename)).toEqual(['agreement_001.pdf']);
    expect(store.indexedCount()).toBe(1);
  });

  it('allows searching only when something is indexed', async () => {
    expect(store.canSearch()).toBe(true); // unknown before the first load

    let loading = store.load();
    http.expectOne(`${API_BASE_URL}/documents`).flush({ count: 1, documents: [makeDoc({ status: 'failed' })] });
    await loading;
    expect(store.canSearch()).toBe(false);

    loading = store.load();
    http.expectOne(`${API_BASE_URL}/documents`).flush({ count: 1, documents: [makeDoc()] });
    await loading;
    expect(store.canSearch()).toBe(true);
  });

  it('checks back while a document is still indexing', async () => {
    vi.useFakeTimers();
    try {
      const loading = store.load();
      http.expectOne(`${API_BASE_URL}/documents`).flush({ count: 1, documents: [makeDoc({ status: 'processing' })] });
      await loading;

      await vi.advanceTimersByTimeAsync(3000);
      http.expectOne(`${API_BASE_URL}/documents`).flush({ count: 1, documents: [makeDoc()] });
      await vi.advanceTimersByTimeAsync(0);
      expect(store.documents()[0].status).toBe('indexed');

      await vi.advanceTimersByTimeAsync(10000);
      http.expectNone(`${API_BASE_URL}/documents`); // settled: polling stops
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not list an upload twice when a refresh already picked it up', async () => {
    const uploading = store.add(picked('notes.txt'));
    store.documents.set([makeDoc({ status: 'processing' })]); // refresh mid-upload
    http.expectOne(UPLOAD_URL).flush(makeDoc());
    await uploading;

    expect(store.documents().map((d) => d.status)).toEqual(['indexed']);
  });

  it('uploads a file through uploading, indexing and done', async () => {
    const uploading = store.add(picked('notes.txt'));
    expect(store.uploads()[0].state).toBe('uploading');

    const request = http.expectOne(UPLOAD_URL);
    expect(request.request.body instanceof FormData).toBe(true);
    expect(request.request.reportProgress).toBe(true);

    request.event({ type: HttpEventType.UploadProgress, loaded: 40, total: 100 });
    expect(store.uploads()[0]).toMatchObject({ state: 'uploading', progress: 0.4 });

    request.event({ type: HttpEventType.UploadProgress, loaded: 100, total: 100 });
    expect(store.uploads()[0].state).toBe('indexing'); // bytes sent, backend is embedding

    request.flush(makeDoc({ filename: 'notes.txt', file_type: 'txt' }));
    await uploading;

    expect(store.uploads()[0]).toMatchObject({ state: 'done', fileId: makeDoc().file_id });
    expect(store.documents()[0].filename).toBe('notes.txt');
    expect(store.uploadSummary()).toEqual({ total: 1, done: 1, failed: 0, active: 0 });
  });

  it('sends two files at a time and starts the next when one finishes', async () => {
    const uploading = store.add(picked('a.txt', 'b.txt', 'c.txt'));

    const first = http.match(UPLOAD_URL);
    expect(first.length).toBe(2);
    expect(store.uploads().map((u) => u.state)).toEqual(['uploading', 'uploading', 'queued']);

    first[0].flush(makeDoc({ file_id: 'a' }));
    await settle();
    const third = http.match(UPLOAD_URL);
    expect(third.length).toBe(1);

    first[1].flush(makeDoc({ file_id: 'b' }));
    third[0].flush(makeDoc({ file_id: 'c' }));
    await uploading;
    expect(store.uploadSummary().done).toBe(3);
  });

  it('shows the backend message when an upload is rejected, without offering a retry', async () => {
    const uploading = store.add(picked('copy.txt'));
    http.expectOne(UPLOAD_URL).flush(
      { error: { code: 'duplicate_file', message: "This file was already uploaded as 'notes.txt'." } },
      { status: 409, statusText: 'Conflict' },
    );
    await uploading;

    expect(store.uploads()[0]).toMatchObject({
      state: 'error',
      error: "This file was already uploaded as 'notes.txt'.",
      retryable: false,
    });
  });

  it('retries an upload that failed because the backend was unreachable', async () => {
    const uploading = store.add(picked('notes.txt'));
    http.expectOne(UPLOAD_URL).error(new ProgressEvent('error'), { status: 0 });
    await uploading;
    expect(store.uploads()[0]).toMatchObject({ state: 'error', retryable: true });

    const retrying = store.retryUpload(store.uploads()[0].id);
    http.expectOne(UPLOAD_URL).flush(makeDoc());
    await retrying;
    expect(store.uploads()[0].state).toBe('done');
  });

  it('skips files the backend would reject, without calling it', async () => {
    await store.add([
      ...picked('Contracts/virus.exe', 'Contracts/~$draft.docx'),
      { file: new File([], 'empty.txt'), path: 'Contracts/empty.txt' },
      { file: { name: 'huge.pdf', size: 21 * 1024 * 1024 } as File, path: 'huge.pdf' },
    ]);

    expect(store.skipped()).toEqual([
      { path: 'Contracts/virus.exe', reason: 'Unsupported file type' },
      { path: 'Contracts/~$draft.docx', reason: 'Temporary Office file' },
      { path: 'Contracts/empty.txt', reason: 'Empty file' },
      { path: 'huge.pdf', reason: 'Larger than 20 MB' },
    ]);
    expect(store.uploads()).toEqual([]);
    http.expectNone(UPLOAD_URL);
  });

  it('keeps folder paths and clears finished uploads', async () => {
    const uploading = store.add(picked('Contracts/2024/lease.txt', 'misc.exe'));
    http.expectOne(UPLOAD_URL).flush(makeDoc());
    await uploading;
    expect(store.uploads()[0].path).toBe('Contracts/2024/lease.txt');

    store.clearFinished();
    expect(store.uploads()).toEqual([]);
    expect(store.skipped()).toEqual([]);
  });

  it('deletes a document', async () => {
    store.documents.set([makeDoc()]);
    const removing = store.remove(makeDoc());
    http.expectOne({ method: 'DELETE', url: `${API_BASE_URL}/documents/${makeDoc().file_id}` }).flush(null);
    await removing;

    expect(store.documents()).toEqual([]);
  });

  it('keeps the document and reports why a delete failed', async () => {
    store.documents.set([makeDoc()]);
    const removing = store.remove(makeDoc());
    http.expectOne(`${API_BASE_URL}/documents/${makeDoc().file_id}`).flush(
      { error: { code: 'file_in_use', message: 'The file is open in another program.' } },
      { status: 409, statusText: 'Conflict' },
    );
    await removing;

    expect(store.documents().length).toBe(1);
    expect(store.notice()).toBe('The file is open in another program.');
  });

  it('reindexes a failed document', async () => {
    const failed = makeDoc({ status: 'failed', error_message: 'Could not reach OpenAI' });
    store.documents.set([failed]);

    const reindexing = store.reindex(failed);
    expect(store.documents()[0].status).toBe('processing');
    http.expectOne(`${API_BASE_URL}/documents/${failed.file_id}/reindex`).flush(makeDoc());
    await reindexing;
    await settle();

    expect(store.documents()[0].status).toBe('indexed');
  });
});
