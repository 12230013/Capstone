
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Send } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Sidebar } from "./Dashboard";
import "./dashboard.css";
import "./chat.css";
import CDRNetwork from "./CDRNetwork";
import RelationshipNetwork from "./RelationshipNetwork";

const CDR_KEYWORDS =
  /\b(cdr|call records?|communication records?|call history|communication network|communication patterns?|unusual communication hours|incoming calls?|outgoing calls?|call frequency|call duration|call timeline|interactions)\b/i;

const RELATIONSHIP_KEYWORDS =
  /\b(relationship|relationships|family tree|family members|relatives|degree)\b/i;

// ============================================================
// Markdown formatting
// ============================================================

function formatMarkdown(content) {
  if (typeof content !== "string") {
    return String(content ?? "");
  }

  return content
    // Convert literal escaped newline sequences to actual newlines.
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n");
}

// ============================================================
// Visualization helpers
// ============================================================

function getVisualizationData(visualization) {
  if (!visualization || typeof visualization !== "object") {
    return null;
  }

  const candidates = [
    visualization.data,
    visualization.graph,
    visualization,
  ];

  return (
    candidates.find(
      (candidate) =>
        candidate &&
        typeof candidate === "object" &&
        Array.isArray(candidate.nodes) &&
        Array.isArray(candidate.edges)
    ) ?? null
  );
}

function getVisualizationType(visualization) {
  if (!visualization || typeof visualization !== "object") {
    return "";
  }

  return String(
    visualization.type ??
    visualization.visualization_type ??
    visualization.kind ??
    ""
  ).toLowerCase();
}

function getCdrNetworkVisualization(item) {
  const visualization = item.visualization;
  const data = getVisualizationData(visualization);

  if (!data) return null;

  const type = getVisualizationType(visualization);

  const hasCdrSource = item.sources?.some(
    (source) =>
      /cdr|communication/i.test(
        `${source.type ?? ""} ${source.analysis ?? ""}`
      )
  );

  const isRelationship =
    /relationship|family.?tree/i.test(type);

  const isCdr =
    /cdr|communication.?network|call.?network/i.test(type) ||
    (
      !isRelationship &&
      hasCdrSource &&
      /network/i.test(
        `${type} ${visualization.analysis ?? ""}`
      )
    );

  if (!isCdr) return null;

  return data;
}

function getRelationshipVisualization(item) {
  const visualization = item.visualization;
  const data = getVisualizationData(visualization);

  if (!data) return null;

  const type = getVisualizationType(visualization);

  const isRelationship =
    /relationship|family.?tree/i.test(type);

  if (!isRelationship) return null;

  return data;
}

// ============================================================
// Validation
// ============================================================

function getFrontendValidationError(question) {
  const asksRelationship = RELATIONSHIP_KEYWORDS.test(question);

  if (
    asksRelationship &&
    (
      /\b(?:4|fourth|four)\s*(?:th)?\s*degree\b/i.test(question) ||
      /\bdegree\s*(?:4|four|fourth)\b/i.test(question)
    )
  ) {
    return (
      "Unsupported relationship degree. " +
      "Only degrees 1, 2, and 3 are supported."
    );
  }

  if (CDR_KEYWORDS.test(question)) {
    const numberTokens = question.match(/\b\d+\b/g) || [];

    // Ignore standalone four-digit years.
    const possibleNumbers = numberTokens.filter(
      (number) => number.length !== 4
    );

    if (possibleNumbers.length > 0) {
      const phoneNumber = possibleNumbers.find(
        (number) => number.length >= 5
      );

      if (phoneNumber && !/^[0-9]{8}$/.test(phoneNumber)) {
        return (
          "Invalid phone number. " +
          "Please enter a valid 8-digit phone number and try again."
        );
      }
    }
  }

  return null;
}

// ============================================================
// Error handling
// ============================================================

function getFriendlyErrorMessage(error, question = "") {
  const message =
    typeof error === "string"
      ? error
      : error?.detail || error?.message || "";

  if (/collection not found/i.test(message)) {
    if (CDR_KEYWORDS.test(question)) {
      return (
        "We couldn't retrieve the communication records. " +
        "Please verify the 8-digit phone number. If it is correct, " +
        "the records or CDR service may be unavailable."
      );
    }

    return (
      "We couldn't retrieve the requested information. " +
      "Please try again. If the problem continues, contact your system administrator."
    );
  }

  if (/invalid phone number|8-digit phone number/i.test(message)) {
    return (
      "Invalid phone number. Please enter a valid 8-digit phone number."
    );
  }

  if (
    /only degrees? 1.*2.*3|degree.*not supported|unsupported relationship degree/i.test(
      message
    )
  ) {
    return (
      "Unsupported relationship degree. " +
      "Only degrees 1, 2, and 3 are supported."
    );
  }

  if (/404|no records found|no communication records/i.test(message)) {
    return (
      "No matching records were found. " +
      "Check the target number and try again."
    );
  }

  if (/401|unauthorized/i.test(message)) {
    return "Your session may have expired. Please sign in again.";
  }

  if (/403|forbidden/i.test(message)) {
    return "You don't have permission to access this information.";
  }

  if (/timed out|timeout/i.test(message)) {
    return "The request timed out. Please try again.";
  }

  if (
    /failed to fetch|networkerror|network request failed/i.test(message)
  ) {
    return (
      "Unable to connect to the chatbot server. " +
      "Check that the backend is running and try again."
    );
  }

  return message || "Something went wrong. Please try again.";
}

// ============================================================
// Chat component
// ============================================================

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
  const [canRetry, setCanRetry] = useState(false);
  const [folders, setFolders] = useState([]);

  const submittedInitialQuestion = useRef(false);
  const bottomRef = useRef(null);

  const sendQuestion = useCallback(
    async (rawQuestion) => {
      const question = rawQuestion.trim();

      if (!question || loading) return;

      setChatError("");
      setCanRetry(false);
      setMessage("");

      const validationError =
        getFrontendValidationError(question);

      if (validationError) {
        setChatError(validationError);
        return;
      }

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
            body: JSON.stringify({ query: question }),
          }
        );

        let data;

        try {
          data = await response.json();
        } catch {
          data = {};
        }

        // Temporary debugging logs.
        console.log("CHAT API RESPONSE:", data);
        console.log(
          "CHAT VISUALIZATION:",
          data.response?.visualization ?? data.visualization
        );

        if (!response.ok) {
          throw new Error(
            getFriendlyErrorMessage(
              data.detail || data.message || data,
              question
            )
          );
        }

        const answer =
          data.response?.answer ??
          data.answer ??
          data.response ??
          data.message ??
          "The backend returned an unrecognized response format.";

        const answerText =
          typeof answer === "string"
            ? answer
            : JSON.stringify(answer);

        if (
          /collection not found/i.test(answerText) ||
          /unsupported relationship degree/i.test(answerText) ||
          /invalid phone number/i.test(answerText)
        ) {
          setChatError(
            getFriendlyErrorMessage(answerText, question)
          );
          return;
        }

        const visualization =
          data.response?.visualization ??
          data.visualization ??
          null;

        setMessages((previous) => [
          ...previous,
          {
            role: "assistant",
            content:
              typeof answer === "string"
                ? answer
                : JSON.stringify(answer, null, 2),
            sources:
              data.response?.sources ??
              data.sources ??
              [],
            visualization,
          },
        ]);
      } catch (error) {
        console.error("Chat error:", error);

        setChatError(
          getFriendlyErrorMessage(error, question)
        );

        setCanRetry(true);
      } finally {
        setLoading(false);
      }
    },
    [loading]
  );

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

  const handleSubmit = (event) => {
    event.preventDefault();

    if (loading || !message.trim()) return;

    sendQuestion(message);
  };

  const startNewConversation = () => {
    setMessages([]);
    setMessage("");
    setChatError("");
    setCanRetry(false);
    submittedInitialQuestion.current = true;

    navigate("/chat", {
      replace: true,
      state: null,
    });
  };

  const createFolder = (name) => {
    if (
      folders.some(
        (folder) =>
          folder.name.toLowerCase() === name.toLowerCase()
      )
    ) {
      window.alert("A folder with this name already exists.");
      return;
    }

    setFolders((previous) => [
      ...previous,
      {
        id: `${Date.now()}-${previous.length}`,
        name,
      },
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

          {messages.map((item, index) => {
            const cdrNetwork =
              item.role === "assistant"
                ? getCdrNetworkVisualization(item)
                : null;

            const relationshipVisualization =
              item.role === "assistant"
                ? getRelationshipVisualization(item)
                : null;

            const targetNumber =
              cdrNetwork?.target_number ??
              cdrNetwork?.phone_number ??
              item.sources?.find(
                (source) => source.type === "CDR analysis"
              )?.phone_number;

            return (
              <div
                key={`${index}-${item.role}`}
                className={`chat-message ${item.role}`}
              >
                {item.role === "assistant" ? (
                  <>
                    <div className="message-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {formatMarkdown(item.content)}
                      </ReactMarkdown>
                    </div>

                    {cdrNetwork && (
                      <CDRNetwork
                        data={cdrNetwork}
                        targetNumber={targetNumber}
                      />
                    )}

                    {relationshipVisualization && (
                      <RelationshipNetwork
                        data={relationshipVisualization}
                      />
                    )}
                  </>
                ) : (
                  <p>{item.content}</p>
                )}

                {item.role === "assistant" &&
                  item.sources?.length > 0 && (
                    <div className="chat-sources">
                      <strong className="chat-sources-title">
                        Sources ({item.sources.length})
                      </strong>

                      {item.sources.map((source, sourceIndex) => (
                        <div
                          key={`${
                            source.doc_id ||
                            source.filename ||
                            source.type ||
                            "source"
                          }-${sourceIndex}`}
                          className="chat-source-item"
                        >
                          {source.type === "CDR analysis" ? (
                            <>
                              <strong>CDR Analytics</strong>

                              {source.phone_number && (
                                <span>
                                  Phone: {source.phone_number}
                                </span>
                              )}

                              {source.analysis && (
                                <span>
                                  Analysis: {source.analysis}
                                </span>
                              )}
                            </>
                          ) : (
                            <>
                              <strong>
                                {source.person_name ||
                                  source.filename ||
                                  source.doc_id ||
                                  source.type ||
                                  `Source ${sourceIndex + 1}`}
                              </strong>

                              {source.case_no && (
                                <span>
                                  Case: {source.case_no}
                                </span>
                              )}

                              {source.statement_date && (
                                <span>
                                  Statement date: {source.statement_date}
                                </span>
                              )}

                              {source.filename && (
                                <span>
                                  Document: {source.filename}
                                </span>
                              )}

                              {source.sentence_ids?.length > 0 && (
                                <span>
                                  Sentence IDs:{" "}
                                  {source.sentence_ids.join(", ")}
                                </span>
                              )}

                              {source.excerpt && (
                                <details className="chat-source-excerpt">
                                  <summary>
                                    View retrieved passage
                                  </summary>
                                  <p>{source.excerpt}</p>
                                </details>
                              )}
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
              </div>
            );
          })}

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

              {canRetry && (
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => {
                    const lastUserMessage = [...messages]
                      .reverse()
                      .find((item) => item.role === "user");

                    if (lastUserMessage) {
                      sendQuestion(lastUserMessage.content);
                    }
                  }}
                >
                  Retry
                </button>
              )}
            </div>
          )}

          <div ref={bottomRef} />
        </section>

        <footer className="chat-prompt-area">
          <form className="prompt-box" onSubmit={handleSubmit}>
            <input
              type="text"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
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
