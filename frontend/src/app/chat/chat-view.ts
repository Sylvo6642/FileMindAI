import { Component, ElementRef, computed, effect, inject, output, signal, viewChild } from '@angular/core';

import { ChatStore } from '../core/chat.store';
import { DocumentsStore } from '../core/documents.store';
import { KeysStore } from '../core/keys.store';
import { Icon } from '../ui/icon';
import { AssistantMessage } from './assistant-message';

const EXAMPLES = [
  'Find the software development agreement between two companies.',
  'Where is the contract about website maintenance?',
  'Find a document mentioning annual support fees.',
  'Find the document related to a payment of 50000 rupees.',
];

@Component({
  selector: 'app-chat-view',
  imports: [Icon, AssistantMessage],
  templateUrl: './chat-view.html',
  host: { class: 'flex h-full min-w-0 flex-1 flex-col bg-canvas' },
})
export class ChatView {
  protected readonly chat = inject(ChatStore);
  protected readonly docs = inject(DocumentsStore);
  protected readonly keys = inject(KeysStore);

  readonly toggleSidebar = output<void>();
  readonly upload = output<void>();

  protected readonly examples = EXAMPLES;
  protected readonly draft = signal('');
  /** Searching needs an indexed document and both API keys. */
  protected readonly canSearch = computed(() => this.docs.canSearch() && this.keys.searchReady());
  protected readonly canSend = computed(
    () => this.draft().trim().length > 0 && !this.chat.busy() && this.canSearch(),
  );
  protected readonly placeholder = computed(() => {
    if (!this.keys.searchReady()) {
      return 'Add your API keys to start searching';
    }
    return this.docs.canSearch()
      ? 'Describe the file you’re looking for…'
      : 'Upload a document to start searching';
  });
  protected readonly title = computed(() => this.chat.turns()[0]?.query ?? 'New search');

  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  private readonly box = viewChild<ElementRef<HTMLTextAreaElement>>('box');

  constructor() {
    // Keep the newest turn in view whenever the thread changes.
    effect(() => {
      this.chat.turns();
      const element = this.scroller()?.nativeElement;
      if (element) {
        requestAnimationFrame(() => element.scrollTo?.({ top: element.scrollHeight, behavior: 'smooth' }));
      }
    });
  }

  protected onDraft(textarea: HTMLTextAreaElement): void {
    this.draft.set(textarea.value);
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }

  protected onEnter(event: Event): void {
    if ((event as KeyboardEvent).shiftKey) {
      return; // Shift+Enter inserts a newline
    }
    event.preventDefault();
    this.send();
  }

  protected send(text = this.draft()): void {
    if (!text.trim() || this.chat.busy() || !this.canSearch()) {
      return;
    }
    this.chat.ask(text);
    this.draft.set('');
    const textarea = this.box()?.nativeElement;
    if (textarea) {
      textarea.value = '';
      textarea.style.height = 'auto';
    }
  }

  focusComposer(): void {
    this.box()?.nativeElement.focus();
  }

  scrollToTurn(id: number): void {
    document.getElementById(`turn-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
