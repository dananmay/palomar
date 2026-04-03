export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number; // Client-side only, for display
}
