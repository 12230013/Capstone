import React, { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Send, Upload } from "lucide-react";
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

  return (
    content
      // Convert literal escaped newline sequences to actual newlines.
      .replace(/\\r\\n/g, "\n")
      .replace(/\\n/g, "\n")
  );
}

// ============================================================
// Visualization helpers
// ============================================================

function getVisualizationData(visualization) {
  if (!visualization || typeof visualization !== "object") {
    return null;
  }

  const candidates = [visualization.data, visualization.graph, visualization];

  return (
    candidates.find(
      (candidate) =>
        candidate &&
        typeof candidate === "object" &&
        Array.isArray(candidate.nodes) &&
        Array.isArray(candidate.edges),
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
      "",
  ).toLowerCase();
}

function getCdrNetworkVisualization(item) {
  const visualization = item.visualization;
  const data = getVisualizationData(visualization);

  if (!data) return null;

  const type = getVisualizationType(visualization);

  const hasCdrSource = item.sources?.some((source) =>
    /cdr|communication/i.test(`${source.type ?? ""} ${source.analysis ?? ""}`),
  );

  const isRelationship = /relationship|family.?tree/i.test(type);

  const isCdr =
    /cdr|communication.?network|call.?network/i.test(type) ||
    (!isRelationship &&
      hasCdrSource &&
      /network/i.test(`${type} ${visualization.analysis ?? ""}`));

  if (!isCdr) return null;

  return data;
}

function getRelationshipVisualization(item) {
  const visualization = item.visualization;
  const data = getVisualizationData(visualization);

  if (!data) return null;

  const type = getVisualizationType(visualization);

  const isRelationship = /relationship|family.?tree/i.test(type);

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
    (/\b(?:4|fourth|four)\s*(?:th)?\s*degree\b/i.test(question) ||
      /\bdegree\s*(?:4|four|fourth)\b/i.test(question))
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
      (number) => number.length !== 4,
    );

    if (possibleNumbers.length > 0) {
      const phoneNumber = possibleNumbers.find((number) => number.length >= 5);

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
    typeof error === "string" ? error : error?.detail || error?.message || "";

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
    return "Invalid phone number. Please enter a valid 8-digit phone number.";
  }

  if (
    /only degrees? 1.*2.*3|degree.*not supported|unsupported relationship degree/i.test(
      message,
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

  if (/failed to fetch|networkerror|network request failed/i.test(message)) {
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
  const { conversationId } = useParams();
  const initialQuestion = location.state?.initialQuestion;
  const initialFolderId = location.state?.folderId;
  const initialConversations = location.state?.conversations || [];
  const initialFolders = location.state?.folders || [];

  const [user] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("accUser") || "null");
    } catch {
      return null;
    }
  });

  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [conversations, setConversations] = useState([
    initialConversations 
  ]);
  const [loading, setLoading] = useState(false);
  const [chatError, setChatError] = useState("");
  const [canRetry, setCanRetry] = useState(false);
  const [folders, setFolders] = useState([
    initialFolders
  ]);

  const submittedInitialQuestion = useRef(false);
  const bottomRef = useRef(null);

  const deleteConversation = async (conversationId) => {
    if (!conversationId) return;

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/api/conversations/${conversationId}`,
        {
          method: "DELETE",
        },
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to delete conversation.");
      }

      // If the currently open conversation was deleted,
      // return the chat area to a fresh conversation.
      if (activeConversationId === conversationId) {
        setMessages([]);
        setMessage("");
        setChatError("");
        setCanRetry(false);
        setActiveConversationId(null);

        navigate("/Dashboard", {
          replace: true,
        });
      }

      await loadConversations();
    } catch (error) {
      console.error("Failed to delete conversation:", error);
      window.alert(error.message || "Unable to delete conversation.");
    }
  };

  const selectConversation = async (conversationId) => {
    if (!conversationId) return;

    try {
      setLoading(true);
      setChatError("");
      setCanRetry(false);

      const response = await fetch(
        `http://127.0.0.1:8000/api/conversations/${conversationId}/messages`,
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load conversation.");
      }

      const loadedMessages = (data.messages || []).map((item) => ({
        role: item.role,
        content: item.content,
        sources: item.sources || [],
        visualization: item.visualization || null,
      }));

      setMessages(loadedMessages);
      setActiveConversationId(conversationId);
      setMessage("");

      navigate(`/chat/${conversationId}`);
    } catch (error) {
      console.error("Failed to load conversation:", error);

      setChatError(error.message || "Unable to load conversation.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!conversationId) {
      return;
    }

    if (conversationId === activeConversationId) {
      return;
    }

    selectConversation(conversationId);
  }, [conversationId]);

  const loadFolders = async () => {
    if (!user?.id) return;

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/api/folders?user_id=${encodeURIComponent(
          user.id,
        )}`,
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load folders.");
      }

      setFolders(data.folders || []);
    } catch (error) {
      console.error("Failed to load folders:", error);
    }
  };

  const loadConversations = async () => {
    if (!user?.id) return;

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/api/conversations?user_id=${encodeURIComponent(
          user.id,
        )}`,
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load conversations.");
      }

      setConversations(data.conversations || []);
    } catch (error) {
      console.error("Failed to load conversations:", error);
    }
  };

  useEffect(() => {
    loadConversations();
    loadFolders();
  }, [user?.id]);

  const sendQuestion = useCallback(
    async (rawQuestion) => {
      const question = rawQuestion.trim();

      if (!question || loading) return;

      setChatError("");
      setCanRetry(false);
      setMessage("");

      const validationError = getFrontendValidationError(question);

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
        const response = await fetch("http://127.0.0.1:8000/api/chat", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            query: question,
            conversation_id: activeConversationId,
            user_id: user?.id,
            folder_id: initialFolderId || null,
          }),
        });

        let data;

        try {
          data = await response.json();
        } catch {
          data = {};
        }

        // Save the conversation ID returned by the backend
        if (data.conversation_id) {
          setActiveConversationId(data.conversation_id);

          navigate(`/chat/${data.conversation_id}`, {
            replace: true,
            state: null,
          });

          await loadConversations();
          await loadFolders();
        }

        if (!response.ok) {
          throw new Error(
            getFriendlyErrorMessage(
              data.detail || data.message || data,
              question,
            ),
          );
        }

        const answer =
          data.response?.answer ??
          data.answer ??
          data.response ??
          data.message ??
          "The backend returned an unrecognized response format.";

        const answerText =
          typeof answer === "string" ? answer : JSON.stringify(answer);

        if (
          /collection not found/i.test(answerText) ||
          /unsupported relationship degree/i.test(answerText) ||
          /invalid phone number/i.test(answerText)
        ) {
          setChatError(getFriendlyErrorMessage(answerText, question));
          return;
        }

        const visualization =
          data.response?.visualization ?? data.visualization ?? null;

        setMessages((previous) => [
          ...previous,
          {
            role: "assistant",
            content:
              typeof answer === "string"
                ? answer
                : JSON.stringify(answer, null, 2),
            sources: data.response?.sources ?? data.sources ?? [],
            visualization,
          },
        ]);
      } catch (error) {
        console.error("Chat error:", error);

        setChatError(getFriendlyErrorMessage(error, question));

        setCanRetry(true);
      } finally {
        setLoading(false);
      }
    },
    [loading, initialFolderId, activeConversationId],
  );

  // Automatically submit a question selected on the dashboard only once.
  useEffect(() => {
    if (!initialQuestion || submittedInitialQuestion.current) {
      return;
    }

    submittedInitialQuestion.current = true;

    sendQuestion(initialQuestion);
  }, [initialQuestion]);

  // Scroll to the latest message as the conversation progresses.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, chatError]);

  const handleSubmit = (event) => {
    event.preventDefault();

    if (loading || !message.trim()) return;

    sendQuestion(message);
  };

  const selectFolder = (folder) => {
    if (!folder?.id) return;

    navigate(`/folders/${folder.id}`);
  };

  const startNewConversation = () => {
    setMessages([]);
    setMessage("");
    setChatError("");
    setCanRetry(false);
    setActiveConversationId(null);
    submittedInitialQuestion.current = false;

    navigate("/Dashboard", {
      replace: true,
    });
  };

  const createFolder = async (name) => {
    if (!user?.id) return;

    try {
      const response = await fetch("http://127.0.0.1:8000/api/folders", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_id: user.id,
          name: name,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to create folder.");
      }

      await loadFolders();
    } catch (error) {
      console.error("Failed to create folder:", error);
    }
  };

  const deleteFolder = (folderId) => {
    if (!window.confirm("Are you sure you want to delete this folder?")) {
      return;
    }

    setFolders((previous) =>
      previous.filter((folder) => folder.id !== folderId),
    );
  };

  const addConversationToFolder = async (folderId, conversationId) => {
    if (!folderId || !conversationId) return;

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/api/folders/${folderId}/conversations`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            conversation_id: conversationId,
          }),
        },
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to add conversation to folder.");
      }

      console.log("CONVERSATION MOVED:", data);

      await loadConversations();
      await loadFolders();
    } catch (error) {
      console.error("Failed to add conversation to folder:", error);
    }
  };

  const activeConversation = conversations.find(
    (conversation) => conversation.id === activeConversationId,
  );

  const formatChatHeaderTime = (dateValue) => {
    if (!dateValue) return "";

    const date = new Date(dateValue);

    if (Number.isNaN(date.getTime())) return "";

    const now = new Date();

    const isToday =
      date.getFullYear() === now.getFullYear() &&
      date.getMonth() === now.getMonth() &&
      date.getDate() === now.getDate();

    const time = date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });

    if (isToday) {
      return `Today - ${time}`;
    }

    const day = date.toLocaleDateString([], {
      month: "short",
      day: "numeric",
      year: "numeric",
    });

    return `${day} - ${time}`;
  };

  return (
    <div className="dashboard chat-page">
      <Sidebar
        folders={folders}
        conversations={conversations}
        onLogoClick={() => navigate("/Dashboard")}
        onCreateFolder={createFolder}
        onDeleteFolder={deleteFolder}
        onSelectFolder={selectFolder}
        onAddConversationToFolder={addConversationToFolder}
        onNewConversation={startNewConversation}
        onSelectConversation={selectConversation}
        onDeleteConversation={deleteConversation}
        activeConversationId={activeConversationId}
        user={user}
      />

      <main className="chat-main-content">
        {activeConversation && (
          <header className="chat-conversation-header">
            <div className="chat-conversation-header-content">
              <h1>{activeConversation.title || "Untitled conversation"}</h1>

              <div className="chat-header-meta">
                <span className="chat-header-status-dot" />

                <span>
                  Started {formatChatHeaderTime(activeConversation.created_at)}
                </span>
              </div>
            </div>
          </header>
        )}

        <section className="conversation-area" aria-live="polite">
          {messages.length === 0 && !loading && (
            <div className="chat-empty-state">
              <h2>How can I help you?</h2>
              <p>
                Ask questions about investigation documents, CDR reports, or
                relationship records.
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
              item.sources?.find((source) => source.type === "CDR analysis")
                ?.phone_number;

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
                      <RelationshipNetwork data={relationshipVisualization} />
                    )}
                  </>
                ) : (
                  <p>{item.content}</p>
                )}

                {item.role === "assistant" && item.sources?.length > 0 && (
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
                              <span>Phone: {source.phone_number}</span>
                            )}

                            {source.analysis && (
                              <span>Analysis: {source.analysis}</span>
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
                              <span>Case: {source.case_no}</span>
                            )}

                            {source.statement_date && (
                              <span>
                                Statement date: {source.statement_date}
                              </span>
                            )}

                            {source.filename && (
                              <span>Document: {source.filename}</span>
                            )}

                            {source.sentence_ids?.length > 0 && (
                              <span>
                                Sentence IDs: {source.sentence_ids.join(", ")}
                              </span>
                            )}

                            {source.excerpt && (
                              <details className="chat-source-excerpt">
                                <summary>View retrieved passage</summary>
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
            <button
              type="button"
              className="upload-button"
              title="File upload will be added later"
              aria-label="Upload file"
              disabled={loading}
              onClick={() =>
                window.alert("File upload will be connected later.")
              }
            >
              <Upload size={20} />
            </button>
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
