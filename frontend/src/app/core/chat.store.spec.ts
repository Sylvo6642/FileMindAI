import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { API_BASE_URL } from './api.config';
import { ChatStore } from './chat.store';
import { HistoryStore } from './history.store';
import { AgentSearchResponse } from './models';

export const SAMPLE_RESPONSE: AgentSearchResponse = {
  query: 'Find the software development agreement',
  answer: 'The software development agreement is most likely agreement_001.pdf.',
  matches: [
    {
      file_id: 'a1b2c3d4-0000-0000-0000-000000000001',
      filename: 'agreement_001.pdf',
      file_type: 'pdf',
      reason: 'Page 1 is titled "Software Development Agreement".',
      similarity: 0.386,
      excerpts: [{ location: 'pages 1-4', text: 'SOFTWARE DEVELOPMENT AGREEMENT between Alpha and Beta.' }],
    },
  ],
  activity: [
    {
      tool: 'search_files',
      input: { query: 'software development agreement', limit: 5 },
      summary: 'Found 5 candidate documents.',
      is_error: false,
    },
  ],
  tool_rounds: 1,
  model: 'claude-haiku-5-5',
  usage: { input_tokens: 4833, output_tokens: 582 },
  search_id: '5e1f0c3a-0000-4000-8000-000000000001',
  created_at: '2026-10-20T09:30:00+00:00',
};

const settle = () => new Promise((resolve) => setTimeout(resolve));

describe('ChatStore', () => {
  let store: ChatStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    store = TestBed.inject(ChatStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('sends the question and stores the answer', async () => {
    store.ask('  Find the software development agreement  ');
    expect(store.busy()).toBe(true);

    const request = http.expectOne(`${API_BASE_URL}/search`);
    expect(request.request.body).toEqual({ query: 'Find the software development agreement' });
    request.flush(SAMPLE_RESPONSE);
    await settle();

    const [turn] = store.turns();
    expect(turn.status).toBe('done');
    expect(turn.response?.matches[0].filename).toBe('agreement_001.pdf');
    expect(store.busy()).toBe(false);
  });

  it('ignores blank questions and questions asked while busy', () => {
    store.ask('   ');
    expect(store.turns()).toEqual([]);

    store.ask('first');
    store.ask('second');
    expect(store.turns().map((t) => t.query)).toEqual(['first']);
    http.expectOne(`${API_BASE_URL}/search`).flush(SAMPLE_RESPONSE);
  });

  it('records a readable error and can retry', async () => {
    store.ask('find it');
    http.expectOne(`${API_BASE_URL}/search`).flush(
      { error: { code: 'assistant_unavailable', message: 'Anthropic rejected the API key.' } },
      { status: 502, statusText: 'Bad Gateway' },
    );
    await settle();
    expect(store.turns()[0]).toMatchObject({ status: 'error', error: 'Anthropic rejected the API key.' });

    store.retry(store.turns()[0].id);
    http.expectOne(`${API_BASE_URL}/search`).flush(SAMPLE_RESPONSE);
    await settle();
    expect(store.turns()[0].status).toBe('done');
  });

  it('explains when the backend is unreachable', async () => {
    store.ask('find it');
    http.expectOne(`${API_BASE_URL}/search`).error(new ProgressEvent('error'), { status: 0 });
    await settle();
    expect(store.turns()[0].error).toContain('Cannot reach the FileMind backend');
  });

  it('adds a finished search to the history list', async () => {
    const history = TestBed.inject(HistoryStore);
    store.ask('Find the software development agreement');
    http.expectOne(`${API_BASE_URL}/search`).flush(SAMPLE_RESPONSE);
    await settle();

    expect(history.searches().map((s) => s.search_id)).toEqual([SAMPLE_RESPONSE.search_id]);
    expect(history.totals()).toEqual({ searches: 1, usage: { input_tokens: 4833, output_tokens: 582 } });
  });

  it('does not list a search the backend did not save', async () => {
    const history = TestBed.inject(HistoryStore);
    store.ask('find it');
    http.expectOne(`${API_BASE_URL}/search`).flush({ ...SAMPLE_RESPONSE, search_id: null, created_at: null });
    await settle();
    expect(history.searches()).toEqual([]);
  });

  it('opens a saved search without running it again', async () => {
    const opening = store.open(SAMPLE_RESPONSE.search_id!);
    http.expectOne(`${API_BASE_URL}/searches/${SAMPLE_RESPONSE.search_id}`).flush(SAMPLE_RESPONSE);
    const id = await opening;

    http.expectNone(`${API_BASE_URL}/search`);
    const [turn] = store.turns();
    expect(turn).toMatchObject({ id, status: 'done', saved: true, query: SAMPLE_RESPONSE.query });
    expect(turn.askedAt.toISOString()).toBe('2026-10-20T09:30:00.000Z');

    // Already in the thread: no second request.
    expect(await store.open(SAMPLE_RESPONSE.search_id!)).toBe(id);
  });

  it('refreshes the history list when a saved search has gone', async () => {
    const opening = store.open('missing');
    http.expectOne(`${API_BASE_URL}/searches/missing`).flush(
      { error: { code: 'search_not_found', message: 'Search not found.' } },
      { status: 404, statusText: 'Not Found' },
    );
    await settle();
    http.expectOne(`${API_BASE_URL}/searches?limit=50`).flush({
      count: 0, searches: [], total_searches: 0, total_usage: { input_tokens: 0, output_tokens: 0 },
    });
    expect(await opening).toBeNull();
    expect(store.turns()).toEqual([]);
  });
});
