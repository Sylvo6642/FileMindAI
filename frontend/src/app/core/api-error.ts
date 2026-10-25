import { HttpErrorResponse } from '@angular/common/http';

/** Turn any HTTP failure into one sentence a user can act on. */
export function describeHttpError(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) {
      return 'Cannot reach the FileMind backend at 127.0.0.1:8000. Is it running?';
    }
    // The backend always answers {"error": {"code": ..., "message": ...}}.
    const message = error.error?.error?.message;
    if (typeof message === 'string' && message) {
      return message;
    }
    if (error.status === 422) {
      return 'The request was not valid.';
    }
  }
  return 'Something went wrong. Please try again.';
}
