import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from './api.config';

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  openai_configured: boolean;
  anthropic_configured: boolean;
}

@Injectable({ providedIn: 'root' })
export class HealthService {
  private readonly http = inject(HttpClient);

  getHealth(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${API_BASE_URL}/health`);
  }
}
