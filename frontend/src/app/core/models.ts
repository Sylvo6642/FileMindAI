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

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface AgentSearchResponse {
  query: string;
  answer: string;
  matches: AgentMatch[];
  activity: ActivityStep[];
  tool_rounds: number;
  model: string | null;
  usage: TokenUsage;
  /** Set once the backend has saved the search to history. */
  search_id?: string | null;
  created_at?: string | null;
}

export interface SearchSummary {
  search_id: string;
  query: string;
  created_at: string;
  match_count: number;
  usage: TokenUsage;
}

export interface SearchHistory {
  count: number;
  searches: SearchSummary[];
  total_searches: number;
  total_usage: TokenUsage;
}
