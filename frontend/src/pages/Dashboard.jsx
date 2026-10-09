
import React, { useState } from "react";
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

function Sidebar({
  folders,
  onCreateFolder,
  onDeleteFolder,
  onNewConversation,
  user,
}) {
  const [showFolderInput, setShowFolderInput] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [activeTab, setActiveTab] = useState("history");
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  const handleCreateFolder = (e) => {
    e.preventDefault();

    const name = folderName.trim();

    if (!name) return;

    onCreateFolder(name);
    setFolderName("");
    setShowFolderInput(false);
  };

  return (
    <aside className="sidebar">
      {/* ACC branding */}
      <div className="logo-section">
        <img
          src="/acc-logo.png"
          alt="Anti-Corruption Commission"
          className="acc-logo"
        />
      </div>

      {/* Sidebar actions */}
      <div className="sidebar-actions">
        <button
          type="button"
          className="sidebar-action"
          onClick={() => setShowFolderInput((previous) => !previous)}
        >
          {showFolderInput ? <X size={17} /> : <FolderPlus size={17} />}
          <span>{showFolderInput ? "Cancel" : "New Folder"}</span>
        </button>

        <button
          type="button"
          className="sidebar-action"
          onClick={onNewConversation}
        >
          <Plus size={17} />
          <span>New Conversation</span>
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

      {/* Folder list */}
      <div className="sidebar-section">
        <div className="sidebar-section-heading">
          <span>YOUR FOLDERS</span>
          <span className="folder-count">{folders.length}</span>
        </div>

        {folders.length === 0 ? (
          <p className="sidebar-empty">Your folders will appear here.</p>
        ) : (
          <div className="folder-list">
            {folders.map((item) => (
              <div className="folder-item" key={item.id}>
                <Folder size={17} />

                <span className="folder-name" title={item.name}>
                  {item.name}
                </span>

                <button
                  type="button"
                  className="delete-folder-button"
                  title={`Delete ${item.name}`}
                  aria-label={`Delete folder ${item.name}`}
                  onClick={() => onDeleteFolder(item.id)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Chat history / activity log */}
      <div className="sidebar-section history-section">
        {activeTab === "history" ? (
          <>
            <div className="sidebar-section-heading">
              <span>RECENT CONVERSATIONS</span>
            </div>

            <div className="empty-history">
              <MessageSquare size={23} />
              <p>No conversations yet</p>
              <span>Start a new conversation to see it here.</span>
            </div>
          </>
        ) : (
          <>
            <div className="sidebar-section-heading">
              <span>ACTIVITY</span>
            </div>

            <div className="empty-history">
              <Clock size={23} />
              <p>No activity yet</p>
              <span>Your recent activity will appear here.</span>
            </div>
          </>
        )}
      </div>

      {/* Decorative Bhutanese dragon.
          Add your image later at public/dragon.png */}
      <div className="sidebar-dragon" aria-hidden="true" />

      {/* User profile */}

      {/* User profile */}

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
    <button
      type="button"
      className="feature-card"
      onClick={onClick}
    >
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
    <button
      type="button"
      className="suggestion-card"
      onClick={onClick}
    >
      <span className="suggestion-icon">
        <MessageSquare size={15} />
      </span>

      <span className="suggestion-text">{text}</span>
    </button>
  );
}

export default function Dashboard() {
  const [user] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("accUser") || "null");
    } catch {
      return null;
    }
  });

  const [message, setMessage] = useState("");
  const [folders, setFolders] = useState([]);
  const [conversationStarted, setConversationStarted] = useState(false);

  const createFolder = (name) => {
    const exists = folders.some(
      (folder) => folder.name.toLowerCase() === name.toLowerCase()
    );

    if (exists) {
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
  const confirmed = window.confirm(
    "Are you sure you want to delete this folder?"
  );

  if (!confirmed) return;

  setFolders((previous) =>
    previous.filter((folder) => folder.id !== folderId)
  );
};

  const startNewConversation = () => {
    setMessage("");
    setConversationStarted(false);
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    const question = message.trim();

    if (!question) return;

    setConversationStarted(true);

    // Temporary frontend behaviour.
    // We will connect this to the AI backend later.
    console.log("User question:", question);

    setMessage("");
  };

  const chooseSuggestion = (question) => {
    setMessage(question);
  };

  return (
    <div className="dashboard">
      <Sidebar
        folders={folders}
        onCreateFolder={createFolder}
        onDeleteFolder={deleteFolder}
        onNewConversation={startNewConversation}
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

        {/* Intro message for a new conversation */}
        {conversationStarted && (
          <div className="local-notice">
            <MessageSquare size={16} />
            <span>
              Your question is ready for backend integration. AI responses are
              not connected yet.
            </span>
          </div>
        )}

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
              disabled={!message.trim()}
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