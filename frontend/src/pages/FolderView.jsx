import { apiFetch } from "../api";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Folder, Send, Upload, Trash2, MessageSquare } from "lucide-react";
import { Sidebar } from "./Dashboard";
import "./dashboard.css";
import "./chat.css";

export default function FolderView() {
  const navigate = useNavigate();
  const { folderId } = useParams();

  const [folders, setFolders] = useState([]);
  const [message, setMessage] = useState("");
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [openChatMenu, setOpenChatMenu] = useState(null);
  const [chatPendingDelete, setChatPendingDelete] = useState(null);

  const chatMenuRef = useRef(null);

  const user = JSON.parse(localStorage.getItem("accUser") || "null");

  const loadFolders = async () => {
    if (!user?.id) return;

    try {
      const response = await apiFetch(
        `/api/folders?user_id=${user.id}`,
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load folders.");
      }

      setFolders(Array.isArray(data) ? data : data.folders || []);
    } catch (error) {
      console.error("Failed to load folders:", error);
    }
  };

  const loadConversations = async () => {
    if (!user?.id) return;

    try {
      const response = await apiFetch(
        `/api/conversations?user_id=${user.id}`,
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load conversations.");
      }

      setConversations(Array.isArray(data) ? data : data.conversations || []);
    } catch (error) {
      console.error("Failed to load conversations:", error);
    }
  };

  useEffect(() => {
    if (!openChatMenu) return;

    const handleOutsideClick = (event) => {
      if (chatMenuRef.current && !chatMenuRef.current.contains(event.target)) {
        setOpenChatMenu(null);
        setChatPendingDelete(null);
      }
    };

    const handleEscape = (event) => {
      if (event.key === "Escape") {
        setOpenChatMenu(null);
        setChatPendingDelete(null);
      }
    };

    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [openChatMenu]);

  useEffect(() => {
    const loadPage = async () => {
      setLoading(true);

      await Promise.all([loadFolders(), loadConversations()]);

      setLoading(false);
    };

    loadPage();
  }, [user?.id]);

  const selectedFolder = folders.find((folder) => folder.id === folderId);

  const folderConversations = conversations.filter(
    (conversation) => conversation.folder_id === folderId,
  );

  const selectFolder = (folder) => {
    if (!folder?.id) return;
    navigate(`/folders/${folder.id}`);
  };

  const selectConversation = (conversationId) => {
    navigate(`/chat/${conversationId}`);
  };

  const startNewConversation = () => {
    navigate("/Dashboard");
  };

  const deleteFolder = async (id) => {
    if (!id) return;
    try {
      const response = await apiFetch(`/api/folders/${id}`, { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to delete folder.");
      setFolders((previous) => previous.filter((folder) => folder.id !== id));
      if (id === folderId) navigate("/Dashboard", { replace: true });
      else await loadConversations();
    } catch (error) {
      console.error("Failed to delete folder:", error);
      window.alert(error.message || "Unable to delete folder.");
    }
  };

  const deleteConversation = async (conversationId) => {
    if (!conversationId) return;

    try {
      const response = await apiFetch(
        `/api/conversations/${conversationId}`,
        {
          method: "DELETE",
        },
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to delete conversation.");
      }

      setConversations((previous) =>
        previous.filter((conversation) => conversation.id !== conversationId),
      );

      setOpenChatMenu(null);
      setChatPendingDelete(null);
    } catch (error) {
      console.error("Failed to delete conversation:", error);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    const question = message.trim();

    if (!question || !selectedFolder) return;

    navigate("/chat", {
      state: {
        initialQuestion: question,
        folderId: selectedFolder.id,
      },
    });
  };

  return (
    <div className="folder-page">
      <Sidebar
        folders={folders}
        conversations={conversations}
        onLogoClick={() => navigate("/Dashboard")}
        onSelectFolder={selectFolder}
        onDeleteFolder={deleteFolder}
        onNewConversation={startNewConversation}
        onSelectConversation={selectConversation}
        activeConversationId={null}
        user={user}
      />

      <main className="folder-main">
        {loading ? (
          <div className="folder-status">Loading folder...</div>
        ) : !selectedFolder ? (
          <div className="folder-status">Folder not found.</div>
        ) : (
          <div className="folder-content">
            {/* Header */}
            <div className="folder-header">
              <h1>{selectedFolder.name}</h1>

              <p className="folder-started">
                Started{" "}
                {selectedFolder.created_at
                  ? new Date(selectedFolder.created_at).toLocaleDateString()
                  : "Recently"}
              </p>
            </div>

            {/* Folder name */}
            <div className="folder-title-row">
              <div className="folder-title-icon">
                <Folder size={22} />
              </div>

              <span>{selectedFolder.name}</span>
            </div>

            {/* Ask box */}
            <footer className="chat-prompt-area folder-chat-prompt-area">
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
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="Ask about investigation documents, CDR, or relationships..."
                  aria-label="Ask the ACC assistant"
                />

                <button
                  type="submit"
                  className="send-button"
                  disabled={!message.trim()}
                  aria-label="Send message"
                >
                  <Send size={19} />
                </button>
              </form>
            </footer>

            {/* Chats */}
            <section className="folder-chats-section">
              <div className="folder-chats-heading">
                <h2>Chats</h2>

                <span>
                  {folderConversations.length}{" "}
                  {folderConversations.length === 1
                    ? "conversation"
                    : "conversations"}
                </span>
              </div>

              {folderConversations.length === 0 ? (
                <div className="folder-empty-chats">
                  <p>No conversations in this folder yet.</p>
                  <span>
                    Add a conversation to this folder from your chat history.
                  </span>
                </div>
              ) : (
                <div className="folder-chat-list">
                  {folderConversations.map((conversation) => (
                    <div
                      key={conversation.id}
                      className="conversation-history-item folder-conversation-item"
                      onClick={() => selectConversation(conversation.id)}
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
                          {conversation.title || "Untitled conversation"}
                        </span>

                        <span className="conversation-history-time">
                          {conversation.updated_at
                            ? new Date(
                                conversation.updated_at,
                              ).toLocaleDateString("en-US", {
                                month: "short",
                                day: "numeric",
                              })
                            : ""}
                        </span>
                      </div>

                      <div
                        className="conversation-menu-wrapper"
                        ref={
                          openChatMenu === conversation.id ? chatMenuRef : null
                        }
                        onClick={(event) => event.stopPropagation()}
                      >
                        <button
                          type="button"
                          className="conversation-menu-button"
                          aria-label="Conversation options"
                          onClick={() => {
                            setOpenChatMenu((current) =>
                              current === conversation.id
                                ? null
                                : conversation.id,
                            );

                            setChatPendingDelete(null);
                          }}
                        >
                          ⋮
                        </button>

                        {openChatMenu === conversation.id && (
                          <div
                            className="conversation-options-menu"
                            onClick={(event) => event.stopPropagation()}
                          >
                            {chatPendingDelete === conversation.id ? (
                              <div className="conversation-delete-confirm">
                                <span className="conversation-delete-text">
                                  Delete this conversation?
                                </span>

                                <div className="conversation-delete-actions">
                                  <button
                                    type="button"
                                    className="conversation-delete-cancel"
                                    onClick={() => {
                                      setChatPendingDelete(null);
                                      setOpenChatMenu(null);
                                    }}
                                  >
                                    Cancel
                                  </button>

                                  <button
                                    type="button"
                                    className="conversation-delete-confirm-button"
                                    onClick={() =>
                                      deleteConversation(conversation.id)
                                    }
                                  >
                                    Delete
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <button
                                type="button"
                                className="conversation-option delete"
                                onClick={() =>
                                  setChatPendingDelete(conversation.id)
                                }
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
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
