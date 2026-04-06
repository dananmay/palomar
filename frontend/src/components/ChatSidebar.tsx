"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Send } from "lucide-react";
import Markdown from "react-markdown";
import { API_BASE } from "@/lib/api";
import type { ChatMessage } from "@/types/chat";

interface Props {
  selectedAnomalyId: string | null;
}

const SUGGESTIONS = ["Brief me", "What's most important right now?", "Any cross-domain connections?"];

export default function ChatSidebar({ selectedAnomalyId }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelName, setModelName] = useState<string | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Check availability on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/chat/status`)
      .then((res) => res.json())
      .then((data) => {
        setAvailable(data.available);
        if (data.model) setModelName(data.model);
        if (!data.available) setConfigError(data.error || "Analyst not available");
      })
      .catch(() => setAvailable(false));
  }, []);

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isLoading) return;

      const userMessage: ChatMessage = {
        role: "user",
        content: text.trim(),
        timestamp: Date.now() / 1000,
      };

      setMessages((prev) => [...prev, userMessage]);
      setInput("");
      setIsLoading(true);
      setError(null);

      // Build history (strip timestamps — backend doesn't need them)
      const history = [...messages, userMessage].map(({ role, content }) => ({
        role,
        content,
      }));

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text.trim(),
            history: history.slice(0, -1), // Don't include the message we just sent (it's the `message` field)
            selected_anomaly_id: selectedAnomalyId,
          }),
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ error: "Request failed" }));
          throw new Error(err.error || `HTTP ${res.status}`);
        }

        const data = await res.json();
        if (data.model) setModelName(data.model);

        const assistantMessage: ChatMessage = {
          role: "assistant",
          content: data.response,
          timestamp: Date.now() / 1000,
        };
        setMessages((prev) => [...prev, assistantMessage]);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "Unknown error";
        setError(msg);
      } finally {
        setIsLoading(false);
      }
    },
    [messages, isLoading, selectedAnomalyId],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <aside className="w-80 h-full flex flex-col border-l border-[#2a2a2a] bg-[#0a0a0a]">
      {/* Header */}
      <div className="px-5 py-4 border-b border-[#2a2a2a]">
        <h1 className="text-base font-semibold text-[#e5e5e5] tracking-tight">Mr. Palomar</h1>
        <div className="flex items-center gap-2 mt-1">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              backgroundColor: available === true ? "#22c55e" : available === false ? "#ef4444" : "#666",
            }}
          />
          <span className="text-xs text-[#666] truncate">
            {modelName
              ? modelName.replace("anthropic/", "").replace("openai/", "").replace("ollama/", "")
              : available === false
                ? "Not configured"
                : "Checking..."}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 && !isLoading ? (
          <EmptyState
            available={available}
            configError={configError}
            onSuggestion={sendMessage}
          />
        ) : (
          <div className="space-y-4">
            {messages.map((msg, i) => (
              <MessageBubble key={i} message={msg} />
            ))}
            {isLoading && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mt-3 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg">
            <div className="text-xs text-red-400">{error}</div>
            <button
              onClick={() => setError(null)}
              className="text-[10px] text-red-500/60 hover:text-red-400 mt-1"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-[#2a2a2a]">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              // Auto-resize
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
            }}
            onKeyDown={handleKeyDown}
            placeholder={available ? "Ask about anomalies..." : "Analyst not configured"}
            disabled={!available || isLoading}
            rows={1}
            className="flex-1 bg-[#141414] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-[#e5e5e5] placeholder-[#555] resize-none focus:outline-none focus:border-[#444] disabled:opacity-40"
            style={{ maxHeight: "120px" }}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || isLoading || !available}
            className="p-2 rounded-lg bg-[#1a1a1a] border border-[#2a2a2a] text-[#666] hover:text-[#e5e5e5] hover:border-[#444] transition-colors disabled:opacity-30 disabled:hover:text-[#666]"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </aside>
  );
}

/* ── Message Bubble ── */

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[90%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
          isUser
            ? "bg-[#1a1a1a] text-[#e5e5e5]"
            : "bg-[#141414] text-[#a3a3a3]"
        }`}
      >
        {isUser ? (
          <span style={{ whiteSpace: "pre-wrap" }}>{message.content}</span>
        ) : (
          <Markdown
            components={{
              h1: ({ children }) => <div className="text-base font-semibold text-[#e5e5e5] mt-3 mb-1">{children}</div>,
              h2: ({ children }) => <div className="text-sm font-semibold text-[#e5e5e5] mt-3 mb-1">{children}</div>,
              h3: ({ children }) => <div className="text-sm font-medium text-[#e5e5e5] mt-2 mb-1">{children}</div>,
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              strong: ({ children }) => <strong className="text-[#e5e5e5] font-medium">{children}</strong>,
              ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>,
              li: ({ children }) => <li>{children}</li>,
              code: ({ children }) => <code className="bg-[#1a1a1a] px-1 py-0.5 rounded text-xs font-mono text-[#e5e5e5]">{children}</code>,
            }}
          >
            {message.content}
          </Markdown>
        )}
      </div>
    </div>
  );
}

/* ── Typing Indicator ── */

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 px-3 py-2">
        <span className="w-1.5 h-1.5 rounded-full bg-[#555] animate-pulse" />
        <span className="w-1.5 h-1.5 rounded-full bg-[#555] animate-pulse" style={{ animationDelay: "0.2s" }} />
        <span className="w-1.5 h-1.5 rounded-full bg-[#555] animate-pulse" style={{ animationDelay: "0.4s" }} />
      </div>
    </div>
  );
}

/* ── Empty State ── */

function EmptyState({
  available,
  configError,
  onSuggestion,
}: {
  available: boolean | null;
  configError: string | null;
  onSuggestion: (text: string) => void;
}) {
  if (available === false) {
    return (
      <div className="flex flex-col items-center justify-center h-full px-6 text-center">
        <div className="text-sm text-[#666] mb-2">Analyst not available</div>
        <div className="text-xs text-[#444]">
          {configError || "Set PALOMAR_ANALYST_MODEL in .env"}
        </div>
      </div>
    );
  }

  if (available === null) {
    return (
      <div className="flex flex-col items-center justify-center h-full">
        <div className="w-6 h-6 rounded-full border-2 border-[#2a2a2a] border-t-[#666] animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-full px-6 text-center">
      <div className="text-sm text-[#666] mb-4">
        Ask about the anomalies you&apos;re seeing
      </div>
      <div className="flex flex-col gap-2 w-full">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onSuggestion(s)}
            className="px-3 py-2 text-xs text-[#888] bg-[#141414] border border-[#2a2a2a] rounded-lg hover:bg-[#1a1a1a] hover:text-[#a3a3a3] transition-colors text-left"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
