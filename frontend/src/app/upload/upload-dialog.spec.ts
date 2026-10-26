import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { API_BASE_URL } from '../core/api.config';
import { makeDoc } from '../core/documents.store.spec';
import { KeysStore } from '../core/keys.store';
import { UploadEstimate } from '../core/models';
import { UploadDialog, formatCost } from './upload-dialog';

const ESTIMATE_URL = `${API_BASE_URL}/documents/estimate`;
const UPLOAD_URL = `${API_BASE_URL}/documents/upload`;

const settle = () => new Promise((resolve) => setTimeout(resolve));

function estimate(overrides: Partial<UploadEstimate> = {}): UploadEstimate {
  return {
    filename: 'lease.pdf',
    file_type: 'pdf',
    size_bytes: 5000,
    page_count: 4,
    chunk_count: 3,
    token_count: 1500,
    estimated_cost_usd: 0.00003,
    embedding_model: 'text-embedding-3-small',
    duplicate_of: null,
    ...overrides,
  };
}

/** A drop with plain files (no folder entries), as some browsers deliver it. */
function dropOf(...names: string[]): DataTransfer {
  return { items: [], files: names.map((name) => new File(['hello'], name)) } as unknown as DataTransfer;
}

describe('UploadDialog review step', () => {
  let fixture: ComponentFixture<UploadDialog>;
  let http: HttpTestingController;
  let el: HTMLElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [UploadDialog],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(UploadDialog);
    el = fixture.nativeElement;
    await fixture.whenStable();
  });

  afterEach(() => http.verify());

  async function render() {
    await settle();
    await fixture.whenStable();
  }

  function confirmButton(): HTMLButtonElement {
    return Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Upload & embed'))!;
  }

  it('estimates dropped files and uploads nothing until confirmed', async () => {
    fixture.componentInstance.dropFiles(dropOf('lease.pdf', 'notes.txt', 'copy.pdf', 'photo.png'));
    await render();

    const requests = http.match(ESTIMATE_URL);
    expect(requests.length).toBe(3); // photo.png is skipped before asking the backend
    http.expectNone(UPLOAD_URL);
    expect(el.textContent).toContain('Calculating 0 of 3');
    expect(confirmButton().disabled).toBe(true);

    requests[0].flush(estimate());
    requests[1].flush(estimate({ filename: 'notes.txt', file_type: 'txt', page_count: null, token_count: 500, estimated_cost_usd: 0.00001 }));
    requests[2].flush(estimate({ filename: 'copy.pdf', duplicate_of: 'lease_2023.pdf' }));
    await render();

    const text = el.textContent!;
    expect(text).toContain('1,500 tokens');
    expect(text).toContain('Already in your library as lease_2023.pdf');
    expect(text).toContain('1 not uploadable');
    expect(text).toContain('2,000'); // total tokens of the two uploadable files
    expect(text).toContain('$0.000040');
    expect(text).toContain('Nothing has been sent to OpenAI yet');
    expect(confirmButton().textContent).toContain('Upload & embed 2 files');
    http.expectNone(UPLOAD_URL);

    confirmButton().click();
    await render();
    const uploads = http.match(UPLOAD_URL);
    expect(uploads.length).toBe(2);
    uploads.forEach((request, i) => request.flush(makeDoc({ file_id: `f${i}` })));
    await render();
    // The duplicate is listed with the other skipped files of this upload.
    expect(el.textContent!.replace(/\s+/g, ' ')).toContain(
      '2 skipped · 1 unsupported file type, 1 already in the library as lease_2023.pdf',
    );
  });

  it('removes a file from the review so it is not uploaded', async () => {
    fixture.componentInstance.dropFiles(dropOf('lease.pdf', 'notes.txt'));
    await render();
    const [lease, notes] = http.match(ESTIMATE_URL);
    lease.flush(estimate());
    notes.flush(estimate({ filename: 'notes.txt', file_type: 'txt', token_count: 500, estimated_cost_usd: 0.00001 }));
    await render();
    expect(confirmButton().textContent).toContain('Upload & embed 2 files');

    (el.querySelector('[aria-label="Remove lease.pdf"]') as HTMLButtonElement).click();
    await render();

    expect(el.textContent).not.toContain('lease.pdf');
    expect(el.textContent).toContain('$0.000010');
    expect(confirmButton().textContent).toContain('Upload & embed 1 file');

    confirmButton().click();
    await render();
    const upload = http.expectOne(UPLOAD_URL);
    expect((upload.request.body as FormData).get('file')).toHaveProperty('name', 'notes.txt');
    upload.flush(makeDoc({ filename: 'notes.txt' }));
    await render();
  });

  it('goes back to the drop zone when every file is removed', async () => {
    fixture.componentInstance.dropFiles(dropOf('lease.pdf'));
    await render();
    http.expectOne(ESTIMATE_URL).flush(estimate());
    await render();

    (el.querySelector('[aria-label="Remove lease.pdf"]') as HTMLButtonElement).click();
    await render();

    expect(el.textContent).toContain('Drag files or a folder here');
    http.expectNone(UPLOAD_URL);
  });

  it('estimates without an OpenAI key but only uploads once one is added', async () => {
    const keys = TestBed.inject(KeysStore);
    keys.status.set({ openai: { configured: false, hint: null }, anthropic: { configured: true, hint: 'sk-…B' } });
    let asked = 0;
    fixture.componentInstance.addKey.subscribe(() => asked++);

    fixture.componentInstance.dropFiles(dropOf('lease.pdf'));
    await render();
    http.expectOne(ESTIMATE_URL).flush(estimate()); // counting tokens is local: no key needed
    await render();

    expect(el.textContent).toContain('Add your OpenAI API key to upload these files.');
    expect(confirmButton().disabled).toBe(true);
    (Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Add key') as HTMLButtonElement).click();
    expect(asked).toBe(1);

    keys.status.set({ openai: { configured: true, hint: 'sk-…A' }, anthropic: { configured: true, hint: 'sk-…B' } });
    await render();
    expect(confirmButton().disabled).toBe(false);
  });

  it('cancelling the review uploads nothing', async () => {
    fixture.componentInstance.dropFiles(dropOf('lease.pdf'));
    await render();
    http.expectOne(ESTIMATE_URL).flush(estimate());
    await render();

    const cancel = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Cancel')!;
    cancel.click();
    await render();

    http.expectNone(UPLOAD_URL);
    expect(el.textContent).toContain('Drag files or a folder here');
  });

  it('keeps unreadable files out of the upload', async () => {
    fixture.componentInstance.dropFiles(dropOf('scan.pdf'));
    await render();
    http.expectOne(ESTIMATE_URL).flush(
      { error: { code: 'extraction_failed', message: 'This PDF has no text layer.' } },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await render();

    expect(el.textContent).toContain('This PDF has no text layer.');
    expect(el.textContent).toContain('None of these files can be uploaded.');
    expect(confirmButton().disabled).toBe(true);
  });
});

describe('formatCost', () => {
  it('keeps tiny amounts readable instead of rounding them away', () => {
    expect(formatCost(0)).toBe('$0.00');
    expect(formatCost(0.00003)).toBe('$0.000030');
    expect(formatCost(0.004)).toBe('$0.0040');
    expect(formatCost(1.234)).toBe('$1.23');
  });
});
