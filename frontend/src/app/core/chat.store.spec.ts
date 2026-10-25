import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { API_BASE_URL } from './api.config';
import { ChatStore } from './chat.store';
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
});
