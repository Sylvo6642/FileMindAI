import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { App } from './app';
import { API_BASE_URL } from './core/api.config';

describe('App', () => {
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  function statusText(fixture: ReturnType<typeof TestBed.createComponent<App>>): string {
    const el = fixture.nativeElement as HTMLElement;
    return el.querySelector('[data-testid="backend-status"]')?.textContent ?? '';
  }

  it('shows OK when the backend health check succeeds', async () => {
    const fixture = TestBed.createComponent(App);
    httpMock.expectOne(`${API_BASE_URL}/health`).flush({
      status: 'ok',
      app: 'FileMind AI',
      version: '0.1.0',
      openai_configured: false,
      anthropic_configured: false,
    });
    await fixture.whenStable();
    expect(statusText(fixture)).toContain('Backend: OK');
  });

  it('shows unreachable when the backend is down', async () => {
    const fixture = TestBed.createComponent(App);
    httpMock
      .expectOne(`${API_BASE_URL}/health`)
      .error(new ProgressEvent('error'), { status: 0, statusText: 'Unknown Error' });
    await fixture.whenStable();
    expect(statusText(fixture)).toContain('Backend: unreachable');
  });
});
