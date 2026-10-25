import { Component, inject, signal } from '@angular/core';

import { HealthResponse, HealthService } from './core/health.service';

type BackendState = 'checking' | 'ok' | 'error';

@Component({
  imports: [],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  private readonly healthService = inject(HealthService);

  protected readonly state = signal<BackendState>('checking');
  protected readonly health = signal<HealthResponse | null>(null);

  constructor() {
    this.checkBackend();
  }

  protected checkBackend(): void {
    this.state.set('checking');
    this.healthService.getHealth().subscribe({
      next: (response) => {
        this.health.set(response);
        this.state.set('ok');
      },
      error: () => {
        this.health.set(null);
        this.state.set('error');
      },
    });
  }
}
