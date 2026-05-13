// Shared types between client and server.

export type ContentBlock =
  | { type: 'text'; text: string }
  | {
      type: 'tool_use';
      id?: string;
      name: string;
      input: unknown;
      output?: unknown;
      status: 'pending' | 'success' | 'error';
    };

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string | ContentBlock[];
  createdAt: string;
}

export interface Conversation {
  id: string;
  title: string;
  updatedAt: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  /** raw entity payload from Graphiti */
  attrs?: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  validFrom?: string;
  validTo?: string;
}

export interface Neighborhood {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface DraftRow {
  id: string;
  createdAt: string;
  targetPersona: string | null;
  targetCompany: string | null;
  channel: string | null;
  subject: string | null;
  body: string;
  sentAt: string | null;
  episodeId: string | null;
}
