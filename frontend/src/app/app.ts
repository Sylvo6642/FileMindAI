import { Component, effect, inject, signal, viewChild } from '@angular/core';

import { ChatView } from './chat/chat-view';
import { ChatStore } from './core/chat.store';
import { DocumentsStore } from './core/documents.store';
import { KeysStore } from './core/keys.store';
import { Sidebar } from './layout/sidebar';
import { ApiKeysDialog } from './settings/api-keys-dialog';
import { UploadDialog } from './upload/upload-dialog';

const DESKTOP_QUERY = '(min-width: 768px)';

@Component({
  imports: [Sidebar, ChatView, UploadDialog, ApiKeysDialog],
  selector: 'app-root',
  templateUrl: './app.html',
  host: {
    class: 'block h-full',
    '(dragenter)': 'onDragEnter($event)',
    '(dragover)': '$event.preventDefault()',
    '(drop)': 'onDrop($event)',
  },
})
export class App {
  private readonly docs = inject(DocumentsStore);
  private readonly chat = inject(ChatStore);
  private readonly chatView = viewChild(ChatView);
  private readonly uploadDialog = viewChild.required(UploadDialog);
  private readonly keysDialog = viewChild.required(ApiKeysDialog);
  private readonly keys = inject(KeysStore);
  /** Ask for missing keys once per page load; after "Later" the sidebar offers it again. */
  private keysPrompted = false;

  protected readonly isDesktop = signal(matchMedia(DESKTOP_QUERY).matches);
  protected readonly sidebarOpen = signal(this.isDesktop());

  constructor() {
    void this.docs.load();
    void this.keys.load();
    // A fresh clone has no backend/.env yet: ask for the keys straight away.
    effect(() => {
      if (this.keys.missing().length && !this.keysPrompted) {
        this.keysPrompted = true;
        this.keysDialog().open();
      }
    });
    matchMedia(DESKTOP_QUERY).addEventListener('change', (event) => {
      this.isDesktop.set(event.matches);
      this.sidebarOpen.set(event.matches);
    });
  }

  protected newSearch(): void {
    this.chat.clear();
    this.closeSidebarOnMobile();
    this.chatView()?.focusComposer();
  }

  protected showTurn(id: number): void {
    this.closeSidebarOnMobile();
    this.chatView()?.scrollToTurn(id);
  }

  protected closeSidebarOnMobile(): void {
    if (!this.isDesktop()) {
      this.sidebarOpen.set(false);
    }
  }

  protected openKeys(): void {
    this.closeSidebarOnMobile();
    this.keysDialog().open();
  }

  protected openUpload(): void {
    this.closeSidebarOnMobile();
    this.uploadDialog().open();
  }

  // Dragging files over the window opens the upload dialog, which then takes the drop.
  protected onDragEnter(event: DragEvent): void {
    if (event.dataTransfer?.types.includes('Files')) {
      event.preventDefault();
      this.uploadDialog().open();
    }
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer?.types.includes('Files')) {
      this.uploadDialog().dropFiles(event.dataTransfer);
    }
  }
}
