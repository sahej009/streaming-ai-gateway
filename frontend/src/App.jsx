import { useState } from "react";

export default function App() {
  const [message, setMessage] = useState("");
  const [chatHistory, setChatHistory] = useState([]);
  const [promptVersion, setPromptVersion] = useState("v1");
  const [jiraTicket, setJiraTicket] = useState("");
  const [slackThread, setSlackThread] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);

  const handleSend = async () => {
    if (!message.trim()) return;
    setIsStreaming(true);

    // 1. Add user message to UI
    const newHistory = [...chatHistory, { role: "user", content: message }];
    setChatHistory(newHistory);
    setMessage("");

    try {
      // 2. Silent Auto-Login to get JWT Token
      const authRes = await fetch("http://localhost:8000/auth/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username: "admin", password: "secret123" }),
      });
      const { access_token } = await authRes.json();

      // 3. Prepare an empty assistant message slot
      setChatHistory((prev) => [...prev, { role: "assistant", content: "" }]);

      // 4. Hit the Streaming Endpoint
      const response = await fetch("http://localhost:8000/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${access_token}`,
        },
        body: JSON.stringify({
          message: message,
          session_id: "demo-ui-session",
          prompt_version: promptVersion,
          jira_ticket: jiraTicket || null,
          slack_thread: slackThread || null,
        }),
      });

      // 5. Read the stream token-by-token
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let done = false;

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          const chunk = decoder.decode(value);
          // Parse the "data: {token}\n\n" format
          const lines = chunk.split("\n");
          for (const line of lines) {
            if (line.startsWith("data: ") && line !== "data: [DONE]") {
              const tokenText = line.substring(6);
              // Append token to the last message in history
              setChatHistory((prev) => {
                const updated = [...prev];
                const lastIndex = updated.length - 1;
                updated[lastIndex] = {
                  ...updated[lastIndex],
                  content: updated[lastIndex].content + tokenText,
                };
                return updated;
              });
            }
          }
        }
      }
    } catch (error) {
      console.error("Stream failed:", error);
      setChatHistory((prev) => [
        ...prev,
        { role: "assistant", content: "❌ Connection Error." },
      ]);
    } finally {
      setIsStreaming(false);
    }
  };

  // Raw, developer-tool CSS styling
  return (
    <div
      style={{
        maxWidth: "800px",
        margin: "40px auto",
        fontFamily: "monospace",
        color: "#333",
      }}
    >
      <h2>🚀 Streaming AI Gateway UI</h2>

      {/* Settings Bar */}
      <div
        style={{
          display: "flex",
          gap: "10px",
          marginBottom: "20px",
          padding: "15px",
          background: "#f5f5f5",
          border: "1px solid #ddd",
        }}
      >
        <label>
          <b>Version: </b>
          <select
            value={promptVersion}
            onChange={(e) => setPromptVersion(e.target.value)}
          >
            <option value="v1">v1 (Stable)</option>
            <option value="v2">v2 (Canary)</option>
          </select>
        </label>
        <label>
          <b>Jira Ticket: </b>
          <input
            type="text"
            placeholder="e.g. PROJ-999"
            value={jiraTicket}
            onChange={(e) => setJiraTicket(e.target.value)}
            style={{ width: "100px" }}
          />
        </label>
        <label>
          <b>Slack Thread: </b>
          <input
            type="text"
            placeholder="e.g. C12345"
            value={slackThread}
            onChange={(e) => setSlackThread(e.target.value)}
            style={{ width: "100px" }}
          />
        </label>
      </div>

      {/* Chat History */}
      <div
        style={{
          minHeight: "300px",
          border: "1px solid #ddd",
          padding: "20px",
          marginBottom: "20px",
          background: "#fafafa",
        }}
      >
        {chatHistory.length === 0 && (
          <p style={{ color: "#888" }}>Send a message to start the stream...</p>
        )}
        {chatHistory.map((msg, i) => (
          <div key={i} style={{ marginBottom: "15px" }}>
            <b style={{ color: msg.role === "user" ? "#0066cc" : "#2a9d8f" }}>
              {msg.role === "user" ? "You:" : "AI Gateway:"}
            </b>
            <span style={{ marginLeft: "10px", whiteSpace: "pre-wrap" }}>
              {msg.content}
            </span>
          </div>
        ))}
      </div>

      {/* Input Area */}
      <div style={{ display: "flex", gap: "10px" }}>
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Ask a question..."
          style={{ flex: 1, padding: "10px", fontFamily: "monospace" }}
          disabled={isStreaming}
        />
        <button
          onClick={handleSend}
          disabled={isStreaming}
          style={{
            padding: "10px 20px",
            cursor: "pointer",
            background: "#264653",
            color: "white",
            border: "none",
          }}
        >
          {isStreaming ? "Streaming..." : "Send"}
        </button>
      </div>
    </div>
  );
}
