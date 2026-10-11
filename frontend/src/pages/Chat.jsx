import React, { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Send } from "lucide-react";
import { Sidebar } from "./Dashboard";
import "./dashboard.css";
import "./chat.css";
import CDRNetwork from "./CDRNetwork";
import RelationshipNetwork from "./RelationshipNetwork";

export default function Chat() {
  const location = useLocation();
  const navigate = useNavigate();
  const initialQuestion = location.state?.initialQuestion;

  const [user] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("accUser") || "null");
    } catch {
      return null;
    }
  });

  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [chatError, setChatError] = useState("");
  const [folders, setFolders] = useState([]);

  const submittedInitialQuestion = useRef(false);
  const bottomRef = useRef(null);

  const sendQuestion = useCallback(async (rawQuestion) => {
    const question = rawQuestion.trim();

    if (!question) return;

    setChatError("");
    setMessage("");
    setMessages((previous) => [
      ...previous,
      { role: "user", content: question },
    ]);
    setLoading(true);

    try {
      const response = await fetch(
        "http://127.0.0.1:8000/api/chat",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            query: question,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Failed to get a response from the chatbot."
        );
      }

      const answer =
        data.response?.answer ??
        data.answer ??
        data.response ??
        data.message ??
        "The backend returned an unrecognized response format.";

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            typeof answer === "string"
              ? answer
              : JSON.stringify(answer, null, 2),
          sources: data.response?.sources ?? [],
          visualization: data.response?.visualization ?? null,
        },
      ]);
    } catch (error) {
      console.error("Chat error:", error);
      setChatError(
        error.message || "Unable to connect to the chatbot backend."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  // Automatically submit a question selected on the dashboard.
  useEffect(() => {
    if (initialQuestion && !submittedInitialQuestion.current) {
      submittedInitialQuestion.current = true;
      sendQuestion(initialQuestion);
    }
  }, [initialQuestion, sendQuestion]);

  // Scroll to the latest message as the conversation progresses.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, chatError]);

  const handleSubmit = (e) => {
    e.preventDefault();

    if (loading || !message.trim()) return;

    sendQuestion(message);
  };

  const startNewConversation = () => {
    setMessages([]);
    setMessage("");
    setChatError("");
    submittedInitialQuestion.current = true;
    navigate("/chat", { replace: true, state: null });
  };

  const createFolder = (name) => {
    if (
      folders.some(
        (folder) => folder.name.toLowerCase() === name.toLowerCase()
      )
    ) {
      window.alert("A folder with this name already exists.");
      return;
    }

    setFolders((previous) => [
      ...previous,
      { id: `${Date.now()}-${previous.length}`, name },
    ]);
  };

  const deleteFolder = (folderId) => {
    if (!window.confirm("Are you sure you want to delete this folder?")) {
      return;
    }

    setFolders((previous) =>
      previous.filter((folder) => folder.id !== folderId)
    );
  };

  return (
    <div className="dashboard chat-page">
      <Sidebar
        folders={folders}
        onCreateFolder={createFolder}
        onDeleteFolder={deleteFolder}
        onNewConversation={startNewConversation}
        user={user}
      />

      <main className="chat-main-content">
        <section className="conversation-area" aria-live="polite">
          {messages.length === 0 && !loading && (
            <div className="chat-empty-state">
              <h2>How can I help you?</h2>
              <p>
                Ask questions about investigation documents, CDR reports,
                or relationship records.
              </p>
            </div>
          )}

          {messages.map((item, index) => (
            <div
              key={`${index}-${item.role}`}
              className={`chat-message ${item.role}`}
            >
              <p>{item.content}</p>

              {item.role === "assistant" &&
                item.visualization?.type === "communication_network" && (
                  <CDRNetwork data={item.visualization.data} />
                )}

              {item.role === "assistant" &&
                item.visualization?.type === "relationship_network" && (
                  <RelationshipNetwork data={item.visualization.data} />
                )}

              {item.role === "assistant" && item.sources?.length > 0 && (
                <div className="chat-sources">
                  <strong>Sources</strong>

                  {item.sources.map((source, sourceIndex) => (
                    <div key={sourceIndex} className="chat-source-item">
                      {source.type === "CDR analysis" ? (
                        <>
                          <span>CDR analytics</span>
                          <span>Phone: {source.phone_number}</span>
                          <span>Analysis: {source.analysis}</span>
                        </>
                      ) : (
                        <span>{source.type}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div
              className="chat-message assistant"
              role="status"
              aria-label="Assistant is generating a response"
            >
              <div className="typing-indicator">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}

          {chatError && (
            <div className="chat-error" role="alert">
              <p>{chatError}</p>
              <button
                type="button"
                onClick={() => {
                  const lastUserMessage = [...messages]
                    .reverse()
                    .find((item) => item.role === "user");

                  if (lastUserMessage && !loading) {
                    sendQuestion(lastUserMessage.content);
                  }
                }}
              >
                Retry
              </button>
            </div>
          )}

          <div ref={bottomRef} />
        </section>

        <footer className="chat-prompt-area">
          <form className="prompt-box" onSubmit={handleSubmit}>
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Ask about investigation documents, CDR, or relationships..."
              aria-label="Ask the ACC assistant"
              disabled={loading}
            />

            <button
              type="submit"
              className="send-button"
              disabled={!message.trim() || loading}
              aria-label="Send message"
            >
              <Send size={19} />
            </button>
          </form>

          <p className="disclaimer">
            This AI assistant is a support tool. Verify critical findings
            against official records and cited evidence.
          </p>
        </footer>
      </main>
    </div>
  );
}