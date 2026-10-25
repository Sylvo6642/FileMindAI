import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { App } from './app';
import { API_BASE_URL } from './core/api.config';
import { SAMPLE_RESPONSE } from './core/chat.store.spec';
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

  async function render() {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable(); // first render: the sidebar asks for /health
    http.expectOne(`${API_BASE_URL}/documents`).flush({
      count: 2,
      documents: [makeDoc(), makeDoc({ file_id: 'b2', filename: 'notes.txt', file_type: 'txt', status: 'failed', error_message: 'No key' })],
    });
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
    expect(el.querySelector('[title="No key"]')).not.toBeNull(); // failed status shows its reason
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
});
