import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { API_BASE_URL } from './api.config';
import { DocumentsStore } from './documents.store';
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

  it('uploads a file and adds the indexed record', async () => {
    const uploading = store.uploadFiles([new File(['hello'], 'notes.txt')]);
    expect(store.uploads()[0].state).toBe('uploading');

    const request = http.expectOne(`${API_BASE_URL}/documents/upload`);
    expect(request.request.body instanceof FormData).toBe(true);
    request.flush(makeDoc({ filename: 'notes.txt', file_type: 'txt' }));
    await uploading;

    expect(store.documents()[0].filename).toBe('notes.txt');
    expect(store.uploads()).toEqual([]);
  });

  it('shows the backend message when an upload is rejected', async () => {
    const uploading = store.uploadFiles([new File(['same'], 'copy.txt')]);
    http.expectOne(`${API_BASE_URL}/documents/upload`).flush(
      { error: { code: 'duplicate_file', message: "This file was already uploaded as 'notes.txt'." } },
      { status: 409, statusText: 'Conflict' },
    );
    await uploading;

    expect(store.uploads()[0]).toMatchObject({
      state: 'error',
      error: "This file was already uploaded as 'notes.txt'.",
    });
  });

  it('rejects unsupported or empty files without calling the backend', async () => {
    await store.uploadFiles([new File(['MZ'], 'virus.exe'), new File([], 'empty.txt')]);

    expect(store.uploads().map((u) => u.error)).toEqual([
      'Unsupported file type. Allowed: PDF, DOCX, TXT.',
      'The file is empty.',
    ]);
    http.expectNone(`${API_BASE_URL}/documents/upload`);
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
