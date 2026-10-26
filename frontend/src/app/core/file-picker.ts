/** A file chosen by the user, with its path inside a picked or dropped folder. */
export interface PickedFile {
  file: File;
  path: string;
}

/** Stop walking a dropped folder after this many files, so dropping a whole drive can't hang the page. */
export const MAX_SCANNED_FILES = 5000;

/** Files from <input type="file">; folder pickers fill webkitRelativePath. */
export function filesFromInput(input: HTMLInputElement): PickedFile[] {
  return Array.from(input.files ?? []).map((file) => ({ file, path: file.webkitRelativePath || file.name }));
}

/** Files from a drop, walking dropped folders and their subfolders. */
export async function filesFromDrop(data: DataTransfer): Promise<PickedFile[]> {
  // Take the entries synchronously: the browser empties the DataTransfer once the drop event returns.
  const entries = Array.from(data.items ?? [])
    .filter((item) => item.kind === 'file')
    .map((item) => item.webkitGetAsEntry?.() ?? null);
  if (!entries.length || entries.includes(null)) {
    return Array.from(data.files).map((file) => ({ file, path: file.name }));
  }

  const picked: PickedFile[] = [];
  for (const entry of entries) {
    await walk(entry!, '', picked);
  }
  return picked;
}

async function walk(entry: FileSystemEntry, prefix: string, out: PickedFile[]): Promise<void> {
  if (out.length >= MAX_SCANNED_FILES) {
    return;
  }
  const path = prefix + entry.name;
  if (entry.isFile) {
    try {
      const file = await new Promise<File>((resolve, reject) =>
        (entry as FileSystemFileEntry).file(resolve, reject),
      );
      out.push({ file, path });
    } catch {
      // Unreadable (permissions, file vanished): leave it out.
    }
  } else if (entry.isDirectory && !entry.name.startsWith('.')) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries returns at most ~100 entries per call; keep reading until it returns none.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
      if (!batch.length) {
        break;
      }
      for (const child of batch) {
        await walk(child, path + '/', out);
      }
    }
  }
}
