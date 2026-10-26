import { filesFromDrop } from './file-picker';

/** Minimal stand-ins for the browser's FileSystemEntry API. */
function fileEntry(name: string): FileSystemEntry {
  return {
    name,
    isFile: true,
    isDirectory: false,
    file: (resolve: (file: File) => void) => resolve(new File(['x'], name)),
  } as unknown as FileSystemEntry;
}

function dirEntry(name: string, children: FileSystemEntry[], batchSize = 2): FileSystemEntry {
  return {
    name,
    isFile: false,
    isDirectory: true,
    createReader: () => {
      let offset = 0;
      // Like Chrome, hand out entries in batches and then an empty batch.
      return {
        readEntries: (resolve: (batch: FileSystemEntry[]) => void) => {
          resolve(children.slice(offset, offset + batchSize));
          offset += batchSize;
        },
      };
    },
  } as unknown as FileSystemEntry;
}

function drop(...entries: FileSystemEntry[]): DataTransfer {
  return {
    items: entries.map((entry) => ({ kind: 'file', webkitGetAsEntry: () => entry })),
    files: [],
  } as unknown as DataTransfer;
}

describe('filesFromDrop', () => {
  it('walks dropped folders, subfolders and every batch of entries', async () => {
    const folder = dirEntry('Contracts', [
      fileEntry('a.pdf'),
      fileEntry('b.docx'),
      fileEntry('c.txt'),
      dirEntry('2024', [fileEntry('lease.pdf')]),
    ]);

    const files = await filesFromDrop(drop(folder, fileEntry('loose.txt')));

    expect(files.map((f) => f.path)).toEqual([
      'Contracts/a.pdf',
      'Contracts/b.docx',
      'Contracts/c.txt',
      'Contracts/2024/lease.pdf',
      'loose.txt',
    ]);
  });

  it('skips hidden folders', async () => {
    const files = await filesFromDrop(drop(dirEntry('Docs', [dirEntry('.git', [fileEntry('x.txt')]), fileEntry('y.txt')])));

    expect(files.map((f) => f.path)).toEqual(['Docs/y.txt']);
  });

  it('falls back to the plain file list when entries are unavailable', async () => {
    const file = new File(['x'], 'plain.txt');
    const data = { items: [{ kind: 'file', webkitGetAsEntry: () => null }], files: [file] } as unknown as DataTransfer;

    expect(await filesFromDrop(data)).toEqual([{ file, path: 'plain.txt' }]);
  });
});
