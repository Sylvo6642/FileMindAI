import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { App } from './app';
import { API_BASE_URL } from './core/api.config';
import { SAMPLE_RESPONSE } from './core/chat.store.spec';
import { DocumentsStore } from './core/documents.store';
import { makeDoc } from './core/documents.store.spec';

const settle = () => new Promise((resolve) => setTimeout(resolve));

describe('App', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    // jsdom has no matchMedia; pretend to be a desktop browser.
    vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: () => undefined }));
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.unstubAllGlobals();
  });

  const LIBRARY = [
    makeDoc(),
    makeDoc({ file_id: 'b2', filename: 'notes.txt', file_type: 'txt', status: 'failed', error_message: 'No key' }),
  ];

  async function render(documents = LIBRARY) {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable(); // first render: the sidebar asks for /health
    http.expectOne(`${API_BASE_URL}/documents`).flush({ count: documents.length, documents });
    http.expectOne(`${API_BASE_URL}/health`).flush({
      status: 'ok', app: 'FileMind AI', version: '0.1.0', openai_configured: true, anthropic_configured: true,
    });
    await settle();
    await fixture.whenStable();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  it('shows the library and the empty search state', async () => {
    const { el } = await render();

    expect(el.querySelector('h2')?.textContent).toContain('Find any file by describing it');
    expect(el.textContent).toContain('agreement_001.pdf');
    expect(el.textContent).toContain('notes.txt');
    expect(el.textContent).toContain('Backend connected');
    expect(el.querySelector('[aria-label="No key"]')).not.toBeNull(); // status is announced
    expect(el.textContent).toContain('No key'); // failure reason visible without hovering
  });

  it('disables searching until a document is indexed', async () => {
    const { el } = await render([makeDoc({ status: 'failed', error_message: 'No key' })]);

    const composer = el.querySelector('textarea')!;
    expect(composer.placeholder).toBe('Upload a document to start searching');
    const example = Array.from(el.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('software development agreement'),
    )!;
    expect(example.disabled).toBe(true);
  });

  it('runs a search from an example and renders the answer with match cards', async () => {
    const { fixture, el } = await render();

    const example = Array.from(el.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('software development agreement'),
    )!;
    example.click();
    await fixture.whenStable();
    expect(el.textContent).toContain('Searching your documents');

    http.expectOne(`${API_BASE_URL}/search`).flush(SAMPLE_RESPONSE);
    await settle();
    await fixture.whenStable();

    expect(el.textContent).toContain('most likely agreement_001.pdf');
    expect(el.textContent).toContain('Searched “software development agreement” · Found 5 candidate documents.');
    expect(el.textContent).toContain('Matches (1)');
    expect(el.textContent).toContain('sim 0.39');
    expect(el.textContent).not.toContain('%');
    const open = Array.from(el.querySelectorAll('a')).find((a) => a.textContent?.includes('Open file'))!;
    expect(open.getAttribute('href')).toBe(`${API_BASE_URL}/documents/${SAMPLE_RESPONSE.matches[0].file_id}/open`);
    expect(el.textContent).toContain('Recent searches');
  });

  it('opens the upload dialog and shows queued uploads with skipped files', async () => {
    const { fixture, el } = await render();
    const dialog = el.querySelector('dialog')!;
    expect(dialog.open).toBe(false);

    const button = Array.from(el.querySelectorAll('app-sidebar button')).find((b) =>
      b.textContent?.includes('Upload documents'),
    ) as HTMLButtonElement;
    button.click();
    expect(dialog.open).toBe(true);
    expect(dialog.textContent).toContain('Select folder');

    const store = TestBed.inject(DocumentsStore);
    void store.add([
      { file: new File(['hello'], 'lease.txt'), path: 'Contracts/lease.txt' },
      { file: new File(['x'], 'photo.png'), path: 'Contracts/photo.png' },
    ]);
    await fixture.whenStable();

    expect(dialog.textContent).toContain('lease.txt');
    expect(dialog.textContent).toContain('Contracts');
    expect(dialog.textContent).toContain('1 skipped');
    expect(el.querySelector('app-sidebar')!.textContent).toContain('Uploading · 0 of 1 done');

    http.expectOne(`${API_BASE_URL}/documents/upload`).flush(makeDoc({ file_id: 'new', filename: 'lease.txt' }));
    await settle();
    await fixture.whenStable();
    expect(dialog.textContent).toContain('Indexed');
    expect(dialog.textContent).toContain('1 of 1 done');
  });
});
