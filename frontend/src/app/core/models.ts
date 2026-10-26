// Shapes returned by the FastAPI backend (see backend/app/models).

export type FileType = 'pdf' | 'docx' | 'txt';
export type DocumentStatus = 'pending' | 'processing' | 'indexed' | 'failed';

/** What uploading a file would send to the embedding model (POST /documents/estimate). */
export interface UploadEstimate {
  filename: string;
  file_type: FileType;
  size_bytes: number;
  page_count: number | null;
  chunk_count: number;
  token_count: number;
  estimated_cost_usd: number;
  embedding_model: string;
  /** Name of the library document with identical content; uploading would be rejected. */
  duplicate_of: string | null;
}

export interface DocumentRecord {
  file_id: string;
  filename: string;
  file_type: FileType;
  size_bytes: number;
  sha256: string;
  status: DocumentStatus;
  page_count: number | null;
  char_count: number;
  chunk_count: number;
  warnings: string[];
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentList {
  count: number;
  documents: DocumentRecord[];
}

export interface MatchExcerpt {
  location: string;
  text: string;
}

export interface AgentMatch {
  file_id: string;
  filename: string;
  file_type: FileType;
  reason: string;
  /** 1 - cosine distance of the best chunk. A ranking signal, not confidence. */
  similarity: number | null;
  excerpts: MatchExcerpt[];
}

export interface ActivityStep {
  tool: string;
  input: Record<string, unknown>;
  summary: string;
  is_error: boolean;
}

export interface AgentSearchResponse {
  query: string;
  answer: string;
  matches: AgentMatch[];
  activity: ActivityStep[];
  tool_rounds: number;
  model: string | null;
  usage: { input_tokens: number; output_tokens: number };
}
