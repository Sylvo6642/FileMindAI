import { Component, inject, signal, viewChild } from '@angular/core';

import { ChatView } from './chat/chat-view';
import { ChatStore } from './core/chat.store';
import { DocumentsStore } from './core/documents.store';
import { Sidebar } from './layout/sidebar';
import { Icon } from './ui/icon';

const DESKTOP_QUERY = '(min-width: 768px)';

@Component({
  imports: [Sidebar, ChatView, Icon],
  selector: 'app-root',
  templateUrl: './app.html',
  host: {
    class: 'block h-full',
    '(dragenter)': 'onDragEnter($event)',
    '(dragover)': '$event.preventDefault()',
    '(dragleave)': 'onDragLeave($event)',
    '(drop)': 'onDrop($event)',
  },
})
export class App {
  private readonly docs = inject(DocumentsStore);
  private readonly chat = inject(ChatStore);
  private readonly chatView = viewChild(ChatView);

  protected readonly isDesktop = signal(matchMedia(DESKTOP_QUERY).matches);
  protected readonly sidebarOpen = signal(this.isDesktop());
  protected readonly dragging = signal(false);

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

  protected onDragEnter(event: DragEvent): void {
    if (event.dataTransfer?.types.includes('Files')) {
      event.preventDefault();
      this.dragging.set(true);
    }
  }

  protected onDragLeave(event: DragEvent): void {
    // Only hide the overlay when the pointer leaves the window, not a child element.
    if (!event.relatedTarget) {
      this.dragging.set(false);
    }
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) {
      void this.docs.uploadFiles(files);
    }
  }
}
