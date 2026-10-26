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

  const BOTH_KEYS = {
    openai: { configured: true, hint: 'sk-…AAAA' },
    anthropic: { configured: true, hint: 'sk-…BBBB' },
  };

  const NO_HISTORY = { count: 0, searches: [], total_searches: 0, total_usage: { input_tokens: 0, output_tokens: 0 } };

  async function render(documents = LIBRARY, keys: object = BOTH_KEYS, history: object = NO_HISTORY) {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable(); // first render: the sidebar asks for /health
    http.expectOne(`${API_BASE_URL}/documents`).flush({ count: documents.length, documents });
    http.expectOne(`${API_BASE_URL}/settings/keys`).flush(keys);
    http.expectOne(`${API_BASE_URL}/searches?limit=50`).flush(history);
    http.expectOne(`${API_BASE_URL}/health`).flush({
      status: 'ok', app: 'FileMind AI', version: '0.1.0', openai_configured: true, anthropic_configured: true,
    });
    await settle();
    await fixture.whenStable();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  it('asks for missing API keys on startup and blocks searching until they are added', async () => {
    const { fixture, el } = await render(LIBRARY, {
      openai: { configured: false, hint: null },
      anthropic: { configured: true, hint: 'sk-…BBBB' },
    });
    // Opening the dialog refreshes the key status.
    http.expectOne(`${API_BASE_URL}/settings/keys`).flush({
      openai: { configured: false, hint: null },
      anthropic: { configured: true, hint: 'sk-…BBBB' },
    });
    await settle();
    await fixture.whenStable();

    const keysDialog = el.querySelector('app-api-keys-dialog dialog') as HTMLDialogElement;
    expect(keysDialog.open).toBe(true);
    expect(keysDialog.textContent).toContain('Add your API keys');
    expect(el.querySelector('app-sidebar')!.textContent).toContain('OpenAI API key missing');
    expect(el.querySelector('textarea')!.placeholder).toBe('Add your API keys to start searching');
  });

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
    const sidebar = el.querySelector('app-sidebar')!.textContent!;
    expect(sidebar).toContain('Recent searches');
    expect(sidebar).toContain('5,415 Claude tokens over 1 search');
  });

  const SAVED = {
    count: 1,
    searches: [
      {
        search_id: SAMPLE_RESPONSE.search_id,
        query: SAMPLE_RESPONSE.query,
        created_at: SAMPLE_RESPONSE.created_at,
        match_count: 1,
        usage: SAMPLE_RESPONSE.usage,
      },
    ],
    total_searches: 1,
    total_usage: SAMPLE_RESPONSE.usage,
  };

  it('reopens a saved search from the sidebar without calling Claude', async () => {
    const { fixture, el } = await render(LIBRARY, BOTH_KEYS, SAVED);
    vi.stubGlobal('requestAnimationFrame', () => 0);

    const item = Array.from(el.querySelectorAll('app-sidebar button')).find(
      (b) => b.textContent?.trim() === SAMPLE_RESPONSE.query,
    ) as HTMLButtonElement;
    item.click();
    http.expectOne(`${API_BASE_URL}/searches/${SAMPLE_RESPONSE.search_id}`).flush(SAMPLE_RESPONSE);
    await settle();
    await fixture.whenStable();

    http.expectNone(`${API_BASE_URL}/search`);
    const message = el.querySelector('app-assistant-message')!;
    expect(message.textContent).toContain('most likely agreement_001.pdf');
    expect(message.textContent).toContain('Saved');
    expect(message.textContent).toContain('20 Oct');

    // Run again starts a fresh search for the same question.
    const runAgain = Array.from(message.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Run again'),
    ) as HTMLButtonElement;
    runAgain.click();
    const request = http.expectOne(`${API_BASE_URL}/search`);
    expect(request.request.body).toEqual({ query: SAMPLE_RESPONSE.query });
    request.flush({ ...SAMPLE_RESPONSE, search_id: 'second', created_at: '2026-10-21T10:00:00+00:00' });
    await settle();
  });

  it('marks matches whose file was deleted since the search was saved', async () => {
    const { fixture, el } = await render([makeDoc({ file_id: 'someone-else' })], BOTH_KEYS, SAVED);
    vi.stubGlobal('requestAnimationFrame', () => 0);

    (Array.from(el.querySelectorAll('app-sidebar button')).find(
      (b) => b.textContent?.trim() === SAMPLE_RESPONSE.query,
    ) as HTMLButtonElement).click();
    http.expectOne(`${API_BASE_URL}/searches/${SAMPLE_RESPONSE.search_id}`).flush(SAMPLE_RESPONSE);
    await settle();
    await fixture.whenStable();

    const card = el.querySelector('app-match-card')!;
    expect(card.textContent).toContain('No longer in your library');
    expect(card.querySelector('a')).toBeNull();
  });

  it('clears the history only after a second click', async () => {
    const { fixture, el } = await render(LIBRARY, BOTH_KEYS, SAVED);
    const clear = () =>
      Array.from(el.querySelectorAll('app-sidebar button')).find((b) =>
        b.textContent?.trim().startsWith('Clear'),
      ) as HTMLButtonElement;

    clear().click();
    await fixture.whenStable();
    expect(clear().textContent?.trim()).toBe('Clear all?');
    http.expectNone(`${API_BASE_URL}/searches`);

    clear().click();
    http.expectOne((r) => r.method === 'DELETE' && r.url === `${API_BASE_URL}/searches`).flush({ deleted: 1 });
    await settle();
    await fixture.whenStable();
    expect(el.querySelector('app-sidebar')!.textContent).not.toContain('Recent searches');
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
