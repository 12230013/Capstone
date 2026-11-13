import { apiFetch } from "../api";
import React, { useEffect, useRef, useState } from "react";
import { ChevronLeft, FileText } from "lucide-react";

export default function SourcesPanel({ sources, onClose }) {
  const [selected, setSelected] = useState(null);
  const [document, setDocument] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const firstMatch = useRef(null);
  const closeButton = useRef(null);

  useEffect(() => {
    const previous = window.document.activeElement;
    closeButton.current?.focus();
    const handleKey = event => { if (event.key === "Escape") { event.preventDefault(); onClose(); } };
    window.addEventListener("keydown", handleKey);
    return () => { window.removeEventListener("keydown", handleKey); previous?.focus?.(); };
  }, [onClose]);

  useEffect(() => {
    setDocument(null);
    setError("");
    if (!selected?.doc_id) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    apiFetch("/api/sources/" + encodeURIComponent(selected.doc_id), {
      signal: controller.signal,
    }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to open this document.");
      setDocument(data);
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [selected]);

  useEffect(() => { firstMatch.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [document]);
  const ids = new Set(selected?.sentence_ids || []);
  const firstId = document?.sentences?.find(sentence => ids.has(sentence.id))?.id;
  return <aside className="sources-panel" id="chat-sources-panel" aria-label="Sources">
    <header className="sources-panel-header">
      <button type="button" ref={closeButton} aria-label={selected ? "Back to sources" : "Close sources"} onClick={selected ? () => setSelected(null) : onClose}><ChevronLeft size={16}/></button>
      <h2>{selected ? "DOCUMENT" : "SOURCES"}</h2>
    </header>
    <div className="sources-panel-body">
      {!selected ? sources.map((source, index) => <button type="button" className="source-list-button" key={index} onClick={() => setSelected(source)}>
        <FileText size={19}/><span><strong>{source.filename || source.person_name || source.doc_id || source.type || "Source " + (index + 1)}</strong>
        </span>
      </button>) : <>
        <h3>{selected.filename || selected.person_name || selected.type || "Source"}</h3>
        {selected.case_no && <p className="source-meta">Case: {selected.case_no}</p>}
        {selected.statement_date && <p className="source-meta">Statement date: {selected.statement_date}</p>}
        {selected.phone_number && <p className="source-meta">Phone: {selected.phone_number}</p>}
        {selected.analysis && <p className="source-meta">Analysis: {selected.analysis}</p>}
        {loading && <p role="status">Opening document...</p>}
        {error && <p className="source-notice" role="status">{error}</p>}
        {selected.excerpt && <section className="source-passage"><h4>Referenced passage</h4><p>{selected.excerpt}</p></section>}
        {document && <section className="source-document"><h4>Original document</h4><pre>{document.text}</pre>
          {document.sentences?.length > 0 && <><h4>Sentence references</h4><p className="source-meta">Cited sentences are highlighted below.</p>
            {document.sentences.map(sentence => <p className="source-sentence" key={sentence.id} ref={sentence.id === firstId ? firstMatch : null}>
              <small>{sentence.id}</small>{ids.has(sentence.id) ? <mark>{sentence.text}</mark> : sentence.text}
            </p>)}
          </>}
        </section>}
        {!selected.excerpt && !selected.doc_id && <p className="source-notice">No document passage was returned for this source.</p>}
      </>}
    </div>
  </aside>;
}
