import { useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "YOUR_TEST_TOKEN";
const OUTPUT_COST_PER_TOKEN = 0.08 / 1_000_000;

function TelemetryPill({
  label,
  value,
  bg = "#1e293b",
  color = "#e2e8f0",
  border = "#334155",
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "5px",
        padding: "2px 8px",
        borderRadius: "999px",
        fontSize: "11px",
        fontWeight: 600,
        background: bg,
        color,
        border: `1px solid ${border}`,
        letterSpacing: "0.02em",
      }}
    >
      <span style={{ opacity: 0.7 }}>{label}</span>
      <span>{value}</span>
    </span>
  );
}

export default function App() {
  const [message, setMessage] = useState("");
  const [chatHistory, setChatHistory] = useState([]);
  const [promptVersion, setPromptVersion] = useState("auto");
  const [jiraTicket, setJiraTicket] = useState("");
  const [slackThread, setSlackThread] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);

  // Aggregate live session metrics from completed/streaming assistant turns
  const assistantTurns = chatHistory.filter(
    (m) => m.role === "assistant" && m.telemetry,
  );
  const totalRequests = assistantTurns.length;
  const cacheHits = assistantTurns.filter(
    (m) => m.telemetry.cacheStatus === "HIT",
  ).length;
  const hitRate =
    totalRequests > 0 ? Math.round((cacheHits / totalRequests) * 100) : 0;
  const ttftSamples = assistantTurns
    .map((m) => m.telemetry.ttftMs)
    .filter((v) => typeof v === "number");
  const avgTtftMs =
    ttftSamples.length > 0
      ? Math.round(ttftSamples.reduce((a, b) => a + b, 0) / ttftSamples.length)
      : null;
  const totalCost = assistantTurns.reduce(
    (sum, m) => sum + (m.telemetry.estCost || 0),
    0,
  );

  const handleSend = async () => {
    const trimmed = message.trim();
    if (!trimmed || isStreaming) return;

    setIsStreaming(true);
    setMessage("");

    setChatHistory((prev) => [
      ...prev,
      { role: "user", content: trimmed },
      {
        role: "assistant",
        content: "",
        telemetry: {
          status: "connecting",
          cacheStatus: null,
          promptVersion: null,
          contextInjected: "none",
          ttftMs: null,
          totalMs: null,
          tokensPerSec: null,
          estTokens: 0,
          estCost: 0,
        },
      },
    ]);

    const requestStart = performance.now();

    const updateLastAssistant = (updater) => {
      setChatHistory((prev) => {
        const updated = [...prev];
        const idx = updated.length - 1;
        updated[idx] = updater(updated[idx]);
        return updated;
      });
    };

    try {
      const response = await fetch(`${API_URL}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${API_TOKEN}`,
        },
        body: JSON.stringify({
          message: trimmed,
          session_id: "demo-ui-session",
          prompt_version: promptVersion === "auto" ? "" : promptVersion,
          jira_ticket: jiraTicket.trim() || null,
          slack_thread: slackThread.trim() || null,
        }),
      });

      if (!response.ok) {
        const errBody = await response.text();
        throw new Error(
          `HTTP ${response.status}: ${errBody || response.statusText}`,
        );
      }

      const cacheStatus = response.headers.get("X-Cache") || "UNKNOWN";
      const resolvedVersion =
        response.headers.get("X-Prompt-Version") || promptVersion;
      const contextInjected =
        response.headers.get("X-Context-Injected") || "none";

      updateLastAssistant((msg) => ({
        ...msg,
        telemetry: {
          ...msg.telemetry,
          status: "streaming",
          cacheStatus,
          promptVersion: resolvedVersion,
          contextInjected,
        },
      }));

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let sseBuffer = "";
      let fullText = "";
      let firstTokenAt = null;
      let done = false;

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;

        if (value) {
          sseBuffer += decoder.decode(value, { stream: true });
          const lines = sseBuffer.split("\n");
          sseBuffer = lines.pop() ?? "";

          for (const rawLine of lines) {
            const line = rawLine.replace(/\r$/, "");
            if (!line.startsWith("data: ") || line === "data: [DONE]") continue;

            const tokenText = line.slice(6);
            if (!tokenText) continue;

            const now = performance.now();
            if (firstTokenAt === null) {
              firstTokenAt = now;
            }

            fullText += tokenText;
            const ttftMs = Math.round(firstTokenAt - requestStart);
            const totalMs = Math.round(now - requestStart);
            const estTokens = Math.max(1, Math.round(fullText.length / 4));
            const genSeconds = Math.max((now - firstTokenAt) / 1000, 0.001);
            const tokensPerSec =
              cacheStatus === "HIT" ? null : Math.round(estTokens / genSeconds);
            const estCost =
              cacheStatus === "HIT" ? 0 : estTokens * OUTPUT_COST_PER_TOKEN;

            updateLastAssistant((msg) => ({
              ...msg,
              content: fullText,
              telemetry: {
                ...msg.telemetry,
                status: "streaming",
                ttftMs,
                totalMs,
                tokensPerSec,
                estTokens,
                estCost,
              },
            }));
          }
        }
      }

      const finalMs = Math.round(performance.now() - requestStart);
      const finalTokens = fullText
        ? Math.max(1, Math.round(fullText.length / 4))
        : 0;
      const genSeconds = firstTokenAt
        ? Math.max((performance.now() - firstTokenAt) / 1000, 0.001)
        : Math.max(finalMs / 1000, 0.001);

      updateLastAssistant((msg) => ({
        ...msg,
        telemetry: {
          ...msg.telemetry,
          status: "done",
          totalMs: finalMs,
          estTokens: finalTokens,
          tokensPerSec:
            cacheStatus === "HIT" || finalTokens === 0
              ? null
              : Math.round(finalTokens / genSeconds),
          estCost:
            cacheStatus === "HIT" ? 0 : finalTokens * OUTPUT_COST_PER_TOKEN,
        },
      }));
    } catch (error) {
      console.error("Stream failed:", error);
      updateLastAssistant((msg) => ({
        ...msg,
        content: `❌ ${error.message || "Connection Error."}`,
        telemetry: { ...msg.telemetry, status: "error" },
      }));
    } finally {
      setIsStreaming(false);
    }
  };

  return (
    <div
      style={{
        maxWidth: "900px",
        width: "100%",
        boxSizing: "border-box",
        margin: "32px auto",
        padding: "0 16px",
        textAlign: "left",
        fontFamily:
          "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        color: "#0f172a",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "14px",
        }}
      >
        <h2 style={{ margin: 0 }}>🚀 Streaming AI Gateway Console</h2>
        <button
          onClick={() => setChatHistory([])}
          disabled={isStreaming || chatHistory.length === 0}
          style={{
            padding: "6px 12px",
            fontSize: "12px",
            cursor: "pointer",
            background: "#f1f5f9",
            color: "#334155",
            border: "1px solid #cbd5e1",
            borderRadius: "6px",
            fontFamily: "inherit",
          }}
        >
          Clear Session
        </button>
      </div>

      {/* Live Session Telemetry Strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: "10px",
          marginBottom: "14px",
          padding: "12px",
          background: "#0f172a",
          color: "#f8fafc",
          borderRadius: "8px",
        }}
      >
        <div>
          <div style={{ fontSize: "11px", color: "#94a3b8" }}>REQUESTS</div>
          <div style={{ fontSize: "18px", fontWeight: 700 }}>
            {totalRequests}
          </div>
        </div>
        <div>
          <div style={{ fontSize: "11px", color: "#94a3b8" }}>
            CACHE HIT RATE
          </div>
          <div
            style={{
              fontSize: "18px",
              fontWeight: 700,
              color: hitRate > 0 ? "#4ade80" : "#f8fafc",
            }}
          >
            {hitRate}% ({cacheHits}/{totalRequests})
          </div>
        </div>
        <div>
          <div style={{ fontSize: "11px", color: "#94a3b8" }}>AVG TTFT</div>
          <div style={{ fontSize: "18px", fontWeight: 700, color: "#38bdf8" }}>
            {avgTtftMs !== null ? `${avgTtftMs} ms` : "—"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: "11px", color: "#94a3b8" }}>
            EST. SESSION COST
          </div>
          <div style={{ fontSize: "18px", fontWeight: 700, color: "#fbbf24" }}>
            ${totalCost.toFixed(6)}
          </div>
        </div>
      </div>

      {/* Routing & Context Controls */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "14px",
          alignItems: "center",
          marginBottom: "16px",
          padding: "12px 14px",
          background: "#f8fafc",
          border: "1px solid #e2e8f0",
          borderRadius: "8px",
          fontSize: "13px",
        }}
      >
        <label>
          <b>Routing: </b>
          <select
            value={promptVersion}
            onChange={(e) => setPromptVersion(e.target.value)}
            style={{ padding: "4px 6px", fontFamily: "inherit" }}
          >
            <option value="auto">Auto (Active / Canary)</option>
            <option value="v1">Force v1 (Stable)</option>
            <option value="v2">Force v2 (Canary)</option>
          </select>
        </label>
        <label>
          <b>Jira Ticket: </b>
          <input
            type="text"
            placeholder="PROJ-999"
            value={jiraTicket}
            onChange={(e) => setJiraTicket(e.target.value)}
            style={{
              width: "110px",
              padding: "4px 6px",
              fontFamily: "inherit",
            }}
          />
        </label>
        <label>
          <b>Slack Thread: </b>
          <input
            type="text"
            placeholder="C12345"
            value={slackThread}
            onChange={(e) => setSlackThread(e.target.value)}
            style={{
              width: "110px",
              padding: "4px 6px",
              fontFamily: "inherit",
            }}
          />
        </label>
      </div>

      {/* Chat Stream Window */}
      <div
        style={{
          minHeight: "340px",
          maxHeight: "480px",
          overflowY: "auto",
          border: "1px solid #e2e8f0",
          borderRadius: "8px",
          padding: "18px",
          marginBottom: "14px",
          background: "#ffffff",
        }}
      >
        {chatHistory.length === 0 && (
          <p style={{ color: "#64748b", margin: 0 }}>
            Send a prompt twice (or paraphrase it) to watch live TTFT drop and
            Cache flip from MISS to HIT...
          </p>
        )}

        {chatHistory.map((msg, i) => {
          const t = msg.telemetry;
          const isHit = t?.cacheStatus === "HIT";

          return (
            <div
              key={i}
              style={{
                marginBottom: "16px",
                paddingBottom: "14px",
                borderBottom:
                  i < chatHistory.length - 1 ? "1px solid #f1f5f9" : "none",
              }}
            >
              <div style={{ marginBottom: "6px" }}>
                <b
                  style={{ color: msg.role === "user" ? "#2563eb" : "#0f766e" }}
                >
                  {msg.role === "user" ? "You" : "AI Gateway"}
                </b>
                {t?.status === "streaming" && (
                  <span
                    style={{
                      marginLeft: "8px",
                      fontSize: "11px",
                      color: "#0284c7",
                    }}
                  >
                    ● streaming...
                  </span>
                )}
              </div>

              <div
                style={{
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.5,
                  fontSize: "14px",
                }}
              >
                {msg.content ||
                  (t?.status === "connecting" ? "Connecting..." : "")}
              </div>

              {/* Per-Message Live Telemetry Bar */}
              {msg.role === "assistant" &&
                t &&
                t.status !== "connecting" &&
                t.status !== "error" && (
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "6px",
                      marginTop: "10px",
                    }}
                  >
                    <TelemetryPill
                      label="CACHE"
                      value={t.cacheStatus}
                      bg={isHit ? "#052e16" : "#451a03"}
                      color={isHit ? "#4ade80" : "#fbbf24"}
                      border={isHit ? "#166534" : "#92400e"}
                    />
                    <TelemetryPill
                      label="PROMPT"
                      value={t.promptVersion || "—"}
                      bg="#1e1b4b"
                      color="#a5b4fc"
                      border="#3730a3"
                    />
                    {t.ttftMs !== null && (
                      <TelemetryPill
                        label="TTFT"
                        value={`${t.ttftMs} ms`}
                        bg="#082f49"
                        color="#38bdf8"
                        border="#0369a1"
                      />
                    )}
                    {t.tokensPerSec !== null && (
                      <TelemetryPill
                        label="SPEED"
                        value={`${t.tokensPerSec} tok/s`}
                      />
                    )}
                    {t.totalMs !== null && (
                      <TelemetryPill label="TOTAL" value={`${t.totalMs} ms`} />
                    )}
                    <TelemetryPill
                      label="COST"
                      value={isHit ? "$0 (cached)" : `$${t.estCost.toFixed(6)}`}
                    />
                    {t.contextInjected && t.contextInjected !== "none" && (
                      <TelemetryPill
                        label="CONTEXT"
                        value={t.contextInjected.toUpperCase()}
                        bg="#3b0764"
                        color="#e879f9"
                        border="#7e22ce"
                      />
                    )}
                  </div>
                )}
            </div>
          );
        })}
      </div>

      {/* Input Area */}
      <div style={{ display: "flex", gap: "10px" }}>
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Ask a question (try paraphrasing it on the 2nd send to trigger a semantic cache HIT)..."
          style={{
            flex: 1,
            padding: "10px 12px",
            fontFamily: "inherit",
            border: "1px solid #cbd5e1",
            borderRadius: "6px",
          }}
          disabled={isStreaming}
        />
        <button
          onClick={handleSend}
          disabled={isStreaming}
          style={{
            padding: "10px 20px",
            cursor: isStreaming ? "not-allowed" : "pointer",
            background: isStreaming ? "#64748b" : "#0f172a",
            color: "white",
            border: "none",
            borderRadius: "6px",
            fontFamily: "inherit",
            fontWeight: 600,
          }}
        >
          {isStreaming ? "Streaming..." : "Send"}
        </button>
      </div>
    </div>
  );
}
