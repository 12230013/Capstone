import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Search,
  UserRound,
  ChartNoAxesCombined,
  BookOpen,
  MessageSquare,
  Folder,
  FolderPlus,
  Trash2,
  Upload,
  Send,
  LogOut,
  Clock,
  Activity,
  X,
} from "lucide-react";

import "./dashboard.css";

const features = [
  {
    icon: Search,
    title: "Smart Search",
    description:
      "Search across investigation documents, reports, cases, and records.",
  },
  {
    icon: UserRound,
    title: "Relationship Insights",
    description:
      "Explore relationships between entities, people, organizations and more.",
  },
  {
    icon: ChartNoAxesCombined,
    title: "Data Analysis",
    description:
      "Analyze trends, patterns and key insights from CDR, case records and reports.",
  },
  {
    icon: BookOpen,
    title: "Summarize & Explain",
    description:
      "Get concise summaries, explanations and answers from complex information.",
  },
];

const suggestions = [
  "Show me all calls between Person A and Person B in June 2026",
  "Summarize the statement of witness Tashi Dorji",
  "Find connections between Company X and Company Y",
  "What patterns do you see in the CDR data?",
];

function formatConversationTime(dateValue) {
  if (!dateValue) return "";

  const date = new Date(dateValue);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const now = new Date();

  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  );

  const startOfConversationDay = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );

  const differenceInDays = Math.round(
    (startOfToday - startOfConversationDay) / 86400000,
  );

  const time = date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (differenceInDays === 0) {
    return `Today · ${time}`;
  }

  if (differenceInDays === 1) {
    return `Yesterday · ${time}`;
  }

  const day = date.toLocaleDateString([], {
    month: "short",
    day: "numeric",
  });

  return `${day} · ${time}`;
}

export function Sidebar({
  folders,
  conversations = [],
  onLogoClick,
  onCreateFolder,
  onDeleteFolder,
  onAddConversationToFolder,
  onSelectFolder,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
  activeConversationId,
  user,
}) {
  const [showFolderInput, setShowFolderInput] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [activeTab, setActiveTab] = useState("history");
  const [openConversationMenu, setOpenConversationMenu] = useState(null);
  const [conversationPendingDelete, setConversationPendingDelete] =
    useState(null);
  const [folderPickerConversationId, setFolderPickerConversationId] =
    useState(null);
  const conversationMenuRef = useRef(null);
  const [openFolderMenu, setOpenFolderMenu] = useState(null);
  const [folderPendingDelete, setFolderPendingDelete] = useState(null);
  const folderMenuRef = useRef(null);

  useEffect(() => {
    if (!openConversationMenu) return;

    const handleOutsideClick = (event) => {
      if (
        conversationMenuRef.current &&
        !conversationMenuRef.current.contains(event.target)
      ) {
        setOpenConversationMenu(null);
        setConversationPendingDelete(null);
      }
    };

    const handleEscape = (event) => {
      if (event.key === "Escape") {
        setOpenConversationMenu(null);
        setConversationPendingDelete(null);
      }
    };

    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [openConversationMenu]);

  useEffect(() => {
    if (!openFolderMenu) return;

    const handleOutsideClick = (event) => {
      if (
        folderMenuRef.current &&
        !folderMenuRef.current.contains(event.target)
      ) {
        setOpenFolderMenu(null);
        setFolderPendingDelete(null);
      }
    };

    const handleEscape = (event) => {
      if (event.key === "Escape") {
        setOpenFolderMenu(null);
        setFolderPendingDelete(null);
      }
    };

    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [openFolderMenu]);

  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  const handleCreateFolder = (e) => {
    e.preventDefault();

    const name = folderName.trim();

    if (!name) return;

    onCreateFolder(name);
    setFolderName("");
    setShowFolderInput(false);
  };

  const recentConversations = conversations.filter(
    (conversation) => !conversation.folder_id,
  );

  return (
    <aside className="sidebar">
      {/* ACC branding */}
      <div
        className="logo-section logo-section-clickable"
        onClick={onLogoClick}
        title="Go to Dashboard"
      >
        <img
          src="/acc-logo.png"
          alt="Anti-Corruption Commission"
          className="acc-logo"
        />
      </div>

      {/* Sidebar actions */}
      {/* New folder */}
      <div className="sidebar-actions">
        <button
          type="button"
          className="sidebar-action"
          onClick={() => setShowFolderInput((previous) => !previous)}
        >
          {showFolderInput ? <X size={17} /> : <FolderPlus size={17} />}
          <span>{showFolderInput ? "Cancel" : "New Folder"}</span>
        </button>
      </div>

      {/* Create folder form */}
      {showFolderInput && (
        <form className="folder-create-form" onSubmit={handleCreateFolder}>
          <label htmlFor="folder-name">Folder name</label>

          <input
            id="folder-name"
            type="text"
            value={folderName}
            onChange={(e) => setFolderName(e.target.value)}
            placeholder="Enter folder name"
            autoFocus
            maxLength={50}
          />

          <button type="submit" disabled={!folderName.trim()}>
            Create Folder
          </button>
        </form>
      )}

      {/* Folder list */}
      {folders.length > 0 && (
        <div className="sidebar-quick-folders">
          {folders.map((item) => (
            <div
              key={item.id}
              className="sidebar-quick-folder"
              onClick={() => onSelectFolder?.(item)}
            >
              <Folder size={16} />

              <span title={item.name}>{item.name}</span>

              <div
                className="conversation-menu-wrapper"
                ref={openFolderMenu === item.id ? folderMenuRef : null}
                onClick={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  className="conversation-menu-button folder-menu-button"
                  aria-label="Folder options"
                  onClick={() => {
                    setOpenFolderMenu((current) =>
                      current === item.id ? null : item.id,
                    );

                    setFolderPendingDelete(null);
                  }}
                >
                  ⋮
                </button>

                {openFolderMenu === item.id && (
                  <div className="conversation-options-menu folder-options-menu">
                    {folderPendingDelete === item.id ? (
                      <div className="conversation-delete-confirm">
                        <span className="conversation-delete-text">
                          Delete this folder?
                        </span>

                        <span className="folder-delete-note">
                          Conversations will be kept.
                        </span>

                        <div className="conversation-delete-actions">
                          <button
                            type="button"
                            className="conversation-delete-cancel"
                            onClick={() => {
                              setFolderPendingDelete(null);
                              setOpenFolderMenu(null);
                            }}
                          >
                            Cancel
                          </button>

                          <button
                            type="button"
                            className="conversation-delete-confirm-button"
                            onClick={() => {
                              setFolderPendingDelete(null);
                              setOpenFolderMenu(null);
                              onDeleteFolder(item.id);
                            }}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="conversation-option delete"
                        onClick={() => setFolderPendingDelete(item.id)}
                      >
                        <Trash2 size={16} />
                        <span>Delete</span>
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="sidebar-actions sidebar-new-conversation">
        <button
          type="button"
          className="sidebar-action"
          onClick={onNewConversation}
        >
          <Plus size={17} />
          <span>New Conversation</span>
        </button>
      </div>

      {/* Sidebar tabs */}
      <div className="history-tabs">
        <button
          type="button"
          className={activeTab === "history" ? "active" : ""}
          onClick={() => setActiveTab("history")}
        >
          <MessageSquare size={13} />
          Chat History
        </button>

        <button
          type="button"
          className={activeTab === "activity" ? "active" : ""}
          onClick={() => setActiveTab("activity")}
        >
          <Activity size={13} />
          Activity Log
        </button>
      </div>

      {/* Chat history / activity log */}

      <div className="sidebar-section history-section">
        {activeTab === "history" ? (
          <>
            {recentConversations.length === 0 ? (
              <div className="empty-history">
                <MessageSquare size={23} />
                <p>No conversations yet</p>
                <span>Start a new conversation to see it here.</span>
              </div>
            ) : (
              <div className="conversation-history-list">
                {recentConversations.map((conversation) => (
                  <div
                    key={conversation.id}
                    className={`conversation-history-item ${
                      activeConversationId === conversation.id ? "active" : ""
                    }`}
                    onClick={() => onSelectConversation?.(conversation.id)}
                  >
                    <MessageSquare
                      className="conversation-history-icon"
                      size={17}
                    />

                    <div className="conversation-history-content">
                      <span
                        className="conversation-history-title"
                        title={conversation.title}
                      >
                        {conversation.title}
                      </span>

                      <span className="conversation-history-time">
                        {formatConversationTime(conversation.updated_at)}
                      </span>
                    </div>

                    <div
                      className="conversation-menu-wrapper"
                      ref={
                        openConversationMenu === conversation.id
                          ? conversationMenuRef
                          : null
                      }
                    >
                      <button
                        type="button"
                        className="conversation-menu-button"
                        aria-label="Conversation options"
                        onClick={(event) => {
                          event.stopPropagation();

                          setOpenConversationMenu((current) =>
                            current === conversation.id
                              ? null
                              : conversation.id,
                          );
                        }}
                      >
                        ⋮
                      </button>

                      {openConversationMenu === conversation.id && (
                        <div
                          className="conversation-options-menu"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <button
                            type="button"
                            className="conversation-option"
                            onClick={() => {
                              setFolderPickerConversationId((current) =>
                                current === conversation.id
                                  ? null
                                  : conversation.id,
                              );
                            }}
                          >
                            <Folder size={16} />
                            <span>Add to folder</span>
                          </button>

                          {folderPickerConversationId === conversation.id && (
                            <div className="conversation-folder-picker">
                              {folders.length === 0 ? (
                                <span className="conversation-folder-empty">
                                  No folders available
                                </span>
                              ) : (
                                folders.map((folder) => (
                                  <button
                                    key={folder.id}
                                    type="button"
                                    className="conversation-folder-option"
                                    onClick={async () => {
                                      await onAddConversationToFolder?.(
                                        folder.id,
                                        conversation.id,
                                      );

                                      setFolderPickerConversationId(null);
                                      setOpenConversationMenu(null);
                                    }}
                                  >
                                    <Folder size={15} />
                                    <span>{folder.name}</span>
                                  </button>
                                ))
                              )}
                            </div>
                          )}

                          {conversationPendingDelete === conversation.id ? (
                            <div className="conversation-delete-confirm">
                              <span className="conversation-delete-text">
                                Delete this conversation?
                              </span>

                              <div className="conversation-delete-actions">
                                <button
                                  type="button"
                                  className="conversation-delete-cancel"
                                  onClick={() => {
                                    setConversationPendingDelete(null);
                                    setOpenConversationMenu(null);
                                  }}
                                >
                                  Cancel
                                </button>

                                <button
                                  type="button"
                                  className="conversation-delete-confirm-button"
                                  onClick={() => {
                                    setConversationPendingDelete(null);
                                    setOpenConversationMenu(null);
                                    onDeleteConversation?.(conversation.id);
                                  }}
                                >
                                  Delete
                                </button>
                              </div>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="conversation-option delete"
                              onClick={() => {
                                setConversationPendingDelete(conversation.id);
                              }}
                            >
                              <Trash2 size={16} />
                              <span>Delete</span>
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="empty-history">
              <Clock size={23} />
              <p>No activity yet</p>
              <span>Your recent activity will appear here.</span>
            </div>
          </>
        )}
      </div>

      {/* Decorative Bhutanese dragon.*/}
      <div className="sidebar-dragon" aria-hidden="true" />

      {/* User profile */}
      <div className="sidebar-user">
        <div className="avatar">
          {(user?.name || "U").charAt(0).toUpperCase()}
        </div>

        <div className="user-info">
          <strong>{user?.name || "ACC User"}</strong>
          <span>{user?.role || "ACC Account"}</span>
        </div>

        <button
          type="button"
          className="logout-button"
          title="Log out"
          aria-label="Log out"
          onClick={() => setShowLogoutConfirm((previous) => !previous)}
        >
          <LogOut size={18} />
        </button>
      </div>

      {/* Inline logout confirmation */}
      {showLogoutConfirm && (
        <div className="logout-confirmation">
          <p>Are you sure you want to log out?</p>

          <div className="logout-confirmation-actions">
            <button
              type="button"
              className="logout-cancel-button"
              onClick={() => setShowLogoutConfirm(false)}
            >
              Cancel
            </button>

            <button
              type="button"
              className="logout-confirm-button"
              onClick={() => {
                localStorage.removeItem("accUser");
                window.location.href = "/login";
              }}
            >
              Log Out
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}

function FeatureCard({ icon: Icon, title, description, onClick }) {
  return (
    <button type="button" className="feature-card" onClick={onClick}>
      <div className="feature-icon">
        <Icon size={25} strokeWidth={1.8} />
      </div>

      <h3>{title}</h3>
      <p>{description}</p>
    </button>
  );
}

function SuggestedQuestion({ text, onClick }) {
  return (
    <button type="button" className="suggestion-card" onClick={onClick}>
      <span className="suggestion-icon">
        <MessageSquare size={15} />
      </span>

      <span className="suggestion-text">{text}</span>
    </button>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [user] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("accUser") || "null");
    } catch {
      return null;
    }
  });

  const [message, setMessage] = useState("");
  const [folders, setFolders] = useState([]);
  const [conversations, setConversations] = useState([]);

  const selectFolder = (folder) => {
    if (!folder?.id) return;

    navigate(`/folders/${folder.id}`);
  };

  const [loading, setLoading] = useState(false);

  const loadFolders = async () => {
    if (!user?.id) return;
    console.log("LOAD FOLDERS USER ID:", user?.id);

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
      console.error("Failed to load dashboard conversations:", error);
    }
  };

  useEffect(() => {
    loadConversations();
    loadFolders();
  }, [user?.id]);

  const selectConversation = (conversationId) => {
    if (!conversationId) return;

    navigate(`/chat/${conversationId}`);
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
      window.alert(error.message || "Unable to create folder.");
    }
  };

  const deleteFolder = async (folderId) => {
    if (!folderId) return;

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/api/folders/${folderId}`,
        {
          method: "DELETE",
        },
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to delete folder.");
      }

      await loadFolders();
      await loadConversations();
    } catch (error) {
      console.error("Failed to delete folder:", error);
      window.alert(error.message || "Unable to delete folder.");
    }
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

      await loadConversations();
      await loadFolders();
    } catch (error) {
      console.error("Failed to add conversation to folder:", error);
    }
  };

  const startNewConversation = () => {
    setMessage("");
    navigate("/Dashboard");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    const question = message.trim();

    if (!question) return;

    navigate("/chat", {
      state: {
        initialQuestion: question,
        folders: folders,
        conversations: conversations,
      },
    });
  };

  const chooseSuggestion = (question) => {
    navigate("/chat", {
      state: {
        initialQuestion: question,
        folders: folders,
        conversations: conversations,
      },
    });
  };

  return (
    <div className="dashboard">
      <Sidebar
        folders={folders}
        conversations={conversations}
        onLogoClick={() => navigate("/Dashboard")}
        onCreateFolder={createFolder}
        onDeleteFolder={deleteFolder}
        onAddConversationToFolder={addConversationToFolder}
        onSelectFolder={selectFolder}
        onNewConversation={startNewConversation}
        onSelectConversation={selectConversation}
        activeConversationId={null}
        user={user}
      />

      <main className="main-content">
        {/* Welcome header */}
        <header className="welcome-section">
          <div className="welcome-eyebrow">ANTI-CORRUPTION COMMISSION</div>

          <h1>
            Kuzuzangpo <span className="wave">👋</span>
          </h1>

          <p>
            I'm your AI assistant, helping you search, analyze, and derive
            insights from ACC's investigation documents, records, and data using
            information from CIMS, CDR, the Relationship Mapping System, and the
            Document Repository.
          </p>

          <div className="welcome-badge">
            <span className="status-dot" />
            Investigation Support Assistant
          </div>
        </header>

        {/* Feature cards */}
        <section className="features-section">
          <div className="section-heading">
            <div>
              <h2>How can I help you?</h2>
              <p>Choose a capability to get started.</p>
            </div>
          </div>

          <div className="features-grid">
            {features.map((feature) => (
              <FeatureCard
                key={feature.title}
                icon={feature.icon}
                title={feature.title}
                description={feature.description}
                onClick={() => {
                  chooseSuggestion(
                    `Help me with ${feature.title.toLowerCase()}.`,
                  );
                }}
              />
            ))}
          </div>
        </section>

        {/* Suggested prompts */}
        <section className="suggestions-section">
          <div className="section-heading">
            <div>
              <h2>Try asking something like...</h2>
              <p>Example questions to help you get started.</p>
            </div>
          </div>

          <div className="suggestions-grid">
            {suggestions.map((question) => (
              <SuggestedQuestion
                key={question}
                text={question}
                onClick={() => chooseSuggestion(question)}
              />
            ))}
          </div>
        </section>

        {/* Flexible space */}
        <div className="content-spacer" />

        {/* Chat input */}
        <footer className="prompt-area">
          <form className="prompt-box" onSubmit={handleSubmit}>
            <button
              type="button"
              className="upload-button"
              title="File upload will be added later"
              aria-label="Upload file"
              onClick={() =>
                window.alert("File upload will be connected later.")
              }
            >
              <Upload size={20} />
            </button>

            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Ask about anti-corruption laws, reporting procedures, investigations..."
              aria-label="Ask the ACC assistant"
            />

            <button
              type="submit"
              className="send-button"
              disabled={!message.trim() || loading}
              aria-label="Send message"
              title="Send message"
            >
              <Send size={19} />
            </button>
          </form>

          <p className="disclaimer">
            This AI assistant is a support tool and may provide inaccurate
            information. Always verify critical information with official
            sources.
          </p>
        </footer>
      </main>
    </div>
  );
}
