import { useState, useRef, useEffect } from "react";
import "./App.css";
import accLogo from "./assets/acc-logo.png";
import dzongImg from "./assets/dzong.png";
import dragonImg from "./assets/dragon.png";

// Static mock data — replace with real data from your Auth/CIMS APIs
const CHAT_HISTORY = [
  { id: 1, title: "Bribery case inquiry - Thimphu", meta: "Today · 10:42 AM" },
  { id: 2, title: "Asset declaration non-compliance", meta: "Yesterday · 06:35 PM" },
  { id: 3, title: "Conflict of interest - procurement", meta: "Aug 23 · 06:35 PM" },
];

const ACTIVITY_LOG = [
  { id: 1, title: "Logged in", meta: "Today · 09:58 AM" },
  { id: 2, title: "Queried CDR summary", meta: "Today · 10:41 AM" },
  { id: 3, title: "Viewed case document", meta: "Yesterday · 05:10 PM" },
];

const FEATURE_CARDS = [
  { icon: "🔍", title: "Smart Search", desc: "Search across investigation documents, reports, cases, and records." },
  { icon: "🧑‍🤝‍🧑", title: "Relationship Insights", desc: "Explore relationships between entities, people, organizations and more." },
  { icon: "📊", title: "Data Analysis", desc: "Analyze trends, patterns and key insights from CDR, case records and reports." },
  { icon: "📖", title: "Summarize & Explain", desc: "Get concise summaries, explanations and answers from complex information." },
];

const SUGGESTIONS = [
  "Show me all calls between Person A and Person B in June 2026",
  "Summarize the statement of witness Tashi Dorji",
  "Find connections between Company X and Company Y",
  "What patterns do you see in the CDR data?",
];

// Sidebar --------------------------------------------------------------
function Sidebar({ activeTab, setActiveTab, activeChatId, onNewConversation, onNewFolder, onSelectChat, sidebarOpen }) {
  const list = activeTab === "history" ? CHAT_HISTORY : ACTIVITY_LOG;

  return (
    <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
      <div className="sidebar-watermark">
        <img src={dragonImg} alt="" />
      </div>

      <div className="sidebar-body">
      <div className="brand">
        <img src={accLogo} alt="ACC — Anti-Corruption Commission" className="brand-logo" />
      </div>

      <button className="side-btn" onClick={onNewFolder}>＋ New Folder</button>
      <button className="side-btn" onClick={onNewConversation}>＋ New Conversation</button>

      <div className="tabs">
        <div className={`tab ${activeTab === "history" ? "active" : ""}`} onClick={() => setActiveTab("history")}>
          CHAT HISTORY
        </div>
        <div className={`tab ${activeTab === "log" ? "active" : ""}`} onClick={() => setActiveTab("log")}>
          ACTIVITY LOG
        </div>
      </div>

      <div className="chat-list">
        {list.map((item) => (
          <div
            key={item.id}
            className={`chat-item ${activeTab === "history" && item.id === activeChatId ? "active" : ""}`}
            onClick={() => activeTab === "history" && onSelectChat(item)}
          >
            <span className="ico">{activeTab === "history" ? "💬" : "🕒"}</span>
            <div>
              <div className="title">{item.title}</div>
              <div className="meta">{item.meta}</div>
            </div>
          </div>
        ))}
      </div>

      </div>

      <div className="profile">
        <div className="avatar">DI</div>
        <div>
          <div className="who">Demo Investigator</div>
          <div className="role">Investigator</div>
        </div>
        <div className="logout" title="Log out">⏻</div>
      </div>
    </aside>
  );
}

// Home / hero view -------------------------------------------------------
function HomeView({ onAsk }) {
  return (
    <div className="hero-wrap">
      <img src={dzongImg} alt="" className="dzong-watermark" />
      <div className="hero">
        <h1>Kuzuzangpo <span>👋</span></h1>
        <p>
          I'm your AI assistant, helping you search, analyze, and derive insights from ACC's
          investigation documents, records, and data using information from CIMS, CDR, the
          Relationship Mapping System, and the Document Repository.
        </p>
      </div>

      <div className="cards">
        {FEATURE_CARDS.map((c) => (
          <div className="card" key={c.title}>
            <div className="circ">{c.icon}</div>
            <h3>{c.title}</h3>
            <p>{c.desc}</p>
          </div>
        ))}
      </div>

      <div className="try-label">Try asking something like...</div>
      <div className="suggestions">
        {SUGGESTIONS.map((q) => (
          <div className="sugg" key={q} onClick={() => onAsk(q)}>
            <span className="ico">🔍</span>{q}
          </div>
        ))}
      </div>
    </div>
  );
}

// Chat log view -----------------------------------------------------------
function ChatView({ messages }) {
  const bottomRef = useRef(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="chatlog">
      {messages.map((m, i) => (
        <div className={`msg ${m.role}`} key={i}>
          {m.file && (
            <div className="msg-file">
              <span className="msg-file-ico">📄</span> {m.file.name}
            </div>
          )}
          <div>{m.text}</div>
          {m.metadata && (
            <dl className="document-metadata">
              {Object.entries(m.metadata).map(([label, value]) => (
                <div key={label}>
                  <dt>{label.replaceAll("_", " ")}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

// Selected file preview chip, shown above the input bar before sending
function FilePreview({ file, onRemove, disabled = false }) {
  if (!file) return null;
  const isImage = file.type.startsWith("image/");
  return (
    <div className="file-preview">
      {isImage ? (
        <img src={URL.createObjectURL(file)} alt={file.name} className="file-preview-thumb" />
      ) : (
        <span className="file-preview-ico">📄</span>
      )}
      <div className="file-preview-info">
        <div className="file-preview-name">{file.name}</div>
        <div className="file-preview-size">{(file.size / 1024).toFixed(1)} KB</div>
      </div>
      <button className="file-preview-remove" onClick={onRemove} title="Remove file" disabled={disabled}>✕</button>
    </div>
  );
}

// Main App ------------------------------------------------------------------
export default function App() {
  const [activeTab, setActiveTab] = useState("history");
  const [activeChatId, setActiveChatId] = useState(CHAT_HISTORY[0].id);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const fileInputRef = useRef(null);
  const inChat = messages.length > 0;

  function handleClipClick() {
    fileInputRef.current?.click();
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (file && !uploading) {
      setSelectedFile(file);
      setUploadError("");
    }
    e.target.value = ""; // allow re-selecting the same file later
  }

  async function sendMessage(text) {
    if ((!text.trim() && !selectedFile) || uploading) return;
    const file = selectedFile;
    if (file) {
      setUploading(true);
      setUploadError("");
      const formData = new FormData();
      formData.append("file", file);
      formData.append("uploaded_by", "Demo Investigator");
      let uploaded;

      try {
        const uploadResponse = await fetch("/documents/upload", {
          method: "POST",
          body: formData,
        });
        uploaded = await uploadResponse.json();
        if (!uploadResponse.ok) {
          throw new Error(uploaded.detail || "The document could not be uploaded.");
        }
        setInput("");
        setSelectedFile(null);

        const metadataResponse = await fetch(`/documents/${encodeURIComponent(uploaded.document_id)}`);
        const metadata = await metadataResponse.json();
        if (!metadataResponse.ok) {
          throw new Error(metadata.detail || "The uploaded document metadata could not be retrieved.");
        }

        setMessages((prev) => [
          ...prev,
          { role: "user", text: text.trim(), file },
          { role: "bot", text: "Document uploaded. No OCR has been run.", metadata },
        ]);
      } catch (error) {
        const message = error instanceof Error ? error.message : "The document could not be uploaded.";
        if (uploaded?.document_id) {
          setMessages((prev) => [
            ...prev,
            { role: "user", text: text.trim(), file },
            {
              role: "bot",
              text: `Document uploaded as ${uploaded.document_id}, but metadata retrieval failed: ${message}`,
              metadata: uploaded,
            },
          ]);
        } else {
          setUploadError(message);
        }
      } finally {
        setUploading(false);
      }
      return;
    }

    setMessages((prev) => [...prev, { role: "user", text, file }]);
    setInput("");
    setSelectedFile(null);
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          text: file
            ? `Received "${file.name}" — once the OCR pipeline is connected, its extracted text and a summary will appear here.`
            : "This is a prototype response — connect the RAG backend to return real, cited answers here.",
        },
      ]);
    }, 500);
  }

  function handleNewConversation() {
    setMessages([]);
    setInput("");
    setSelectedFile(null);
    setUploadError("");
  }

  function handleNewFolder() {
    const name = window.prompt("Folder name:");
    if (name) window.alert(`Folder "${name}" created.`);
  }

  function handleSelectChat(item) {
    setActiveChatId(item.id);
    setMessages([{ role: "bot", text: `Loaded conversation: ${item.title}` }]);
  }

  return (
    <div className="app">
      <button className="menu-btn" onClick={() => setSidebarOpen((o) => !o)}>☰</button>

      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        activeChatId={activeChatId}
        onNewConversation={handleNewConversation}
        onNewFolder={handleNewFolder}
        onSelectChat={handleSelectChat}
        sidebarOpen={sidebarOpen}
      />

      <main className="main">
        <div className="content">
          {inChat ? <ChatView messages={messages} /> : <HomeView onAsk={sendMessage} />}
        </div>

        <div className="inputbar-wrap">
          <FilePreview file={selectedFile} onRemove={() => setSelectedFile(null)} disabled={uploading} />

          <div className="inputbar">
            <input
              type="file"
              ref={fileInputRef}
              style={{ display: "none" }}
              accept=".pdf,.png,.jpg,.jpeg"
              disabled={uploading}
              onChange={handleFileChange}
            />
            <span
              className="clip"
              onClick={() => !uploading && handleClipClick()}
              aria-disabled={uploading}
              title="Upload a PDF, PNG, or JPEG document"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 16V4M12 4l-4 4M12 4l4 4" />
                <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
              </svg>
            </span>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendMessage(input)}
              disabled={uploading}
              placeholder={selectedFile ? "Add an optional note for this upload..." : "Ask about anti-corruption laws, reporting procedures, investigations..."}
            />
            <button className="send" onClick={() => sendMessage(input)} disabled={uploading}>
              {uploading ? "…" : "➤"}
            </button>
          </div>
          {uploadError && <div className="upload-error" role="alert">{uploadError}</div>}
          <div className="disclaimer">
            This AI assistant is a support tool and may provide inaccurate information. Always apply professional judgment when using its responses.
          </div>
        </div>
      </main>
    </div>
  );
}