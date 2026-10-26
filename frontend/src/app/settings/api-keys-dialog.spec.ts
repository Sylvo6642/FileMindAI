import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { API_BASE_URL } from '../core/api.config';
import { ApiKeysDialog } from './api-keys-dialog';

const KEYS_URL = `${API_BASE_URL}/settings/keys`;
const NONE_SET = { openai: { configured: false, hint: null }, anthropic: { configured: false, hint: null } };
const KEY = 'sk-proj-' + 'a'.repeat(40) + 'WXYZ';

const settle = () => new Promise((resolve) => setTimeout(resolve));

describe('ApiKeysDialog', () => {
  let fixture: ComponentFixture<ApiKeysDialog>;
  let http: HttpTestingController;
  let el: HTMLElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ApiKeysDialog],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ApiKeysDialog);
    el = fixture.nativeElement;
    await fixture.whenStable();
    fixture.componentInstance.open();
    http.expectOne(KEYS_URL).flush(NONE_SET);
    await render();
  });

  afterEach(() => http.verify());

  async function render() {
    await settle();
    await fixture.whenStable();
  }

  function section(name: string): HTMLElement {
    return Array.from(el.querySelectorAll('section')).find((s) => s.querySelector('h3')?.textContent === name)!;
  }

  async function type(name: string, value: string) {
    const input = section(name).querySelector('input')!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    await render();
  }

  async function submit(name: string) {
    section(name).querySelector('form')!.dispatchEvent(new Event('submit'));
    await render();
  }

  it('shows both providers as not set, with masked inputs', () => {
    expect(el.textContent).toContain('Add your API keys');
    expect(section('OpenAI').textContent).toContain('Not set');
    expect(section('Anthropic').textContent).toContain('Not set');
    expect(section('OpenAI').querySelector('input')!.type).toBe('password');
    expect(el.textContent).toContain('Later');
  });

  it('saves a key and shows only its masked hint', async () => {
    await type('OpenAI', KEY);
    await submit('OpenAI');

    const request = http.expectOne({ method: 'PUT', url: `${KEYS_URL}/openai` });
    expect(request.request.body).toEqual({ key: KEY });
    expect(section('OpenAI').textContent).toContain('Checking…');
    request.flush({ ...NONE_SET, openai: { configured: true, hint: 'sk-…WXYZ' } });
    await render();

    const openai = section('OpenAI');
    expect(openai.textContent).toContain('Set · sk-…WXYZ');
    expect(openai.textContent).toContain('Key checked with OpenAI and saved.');
    expect(openai.querySelector('input')!.value).toBe(''); // the key does not linger in the page
    expect(el.textContent).not.toContain(KEY);
  });

  it('shows why a key was rejected', async () => {
    await type('Anthropic', 'sk-ant-wrong');
    await submit('Anthropic');
    http.expectOne(`${KEYS_URL}/anthropic`).flush(
      { error: { code: 'key_rejected', message: 'Anthropic rejected this key.' } },
      { status: 400, statusText: 'Bad Request' },
    );
    await render();

    expect(section('Anthropic').textContent).toContain('Anthropic rejected this key.');
    expect(section('Anthropic').textContent).toContain('Not set');
  });

  it('can reveal the typed key', async () => {
    await type('OpenAI', KEY);
    (section('OpenAI').querySelector('[aria-label="Show key"]') as HTMLButtonElement).click();
    await render();

    expect(section('OpenAI').querySelector('input')!.type).toBe('text');
  });
});
