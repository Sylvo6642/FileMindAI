import { Component, inject, signal, viewChild } from '@angular/core';

import { ChatView } from './chat/chat-view';
import { ChatStore } from './core/chat.store';
import { DocumentsStore } from './core/documents.store';
import { Sidebar } from './layout/sidebar';
import { UploadDialog } from './upload/upload-dialog';

const DESKTOP_QUERY = '(min-width: 768px)';

@Component({
  imports: [Sidebar, ChatView, UploadDialog],
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

  protected readonly isDesktop = signal(matchMedia(DESKTOP_QUERY).matches);
  protected readonly sidebarOpen = signal(this.isDesktop());

  constructor() {
    void this.docs.load();
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
