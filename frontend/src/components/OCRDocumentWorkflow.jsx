import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { FileText, Upload, X } from "lucide-react";
import "./ocr-document-workflow.css";

const TERMINAL_OCR_STATUSES = new Set(["completed", "not_required", "failed"]);

function errorMessage(data, fallback) {
  if (typeof data?.detail === "string") return data.detail;
  if (typeof data?.message === "string") return data.message;
  return fallback;
}

export default function OCRDocumentWorkflow({ onClose }) {
  const [file, setFile] = useState(null);
  const [documentId, setDocumentId] = useState("");
  const [status, setStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [reviewedPages, setReviewedPages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const alive = useRef(true);

  useEffect(() => () => { alive.current = false; }, []);

  const loadResult = async id => {
    const response = await apiFetch(`/api/ocr/documents/${encodeURIComponent(id)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(errorMessage(data, "Unable to load OCR text."));
    if (!alive.current) return;
    setResult(data);
    setReviewedPages((data.pages || []).map(page => ({
      page_number: page.page_number,
      text: page.text || "",
    })));
  };

  const pollStatus = async id => {
    try {
      const response = await apiFetch(`/api/ocr/documents/${encodeURIComponent(id)}/status`);
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, "Unable to read OCR status."));
      if (!alive.current) return;
      setStatus(data);
      if (data.status === "failed") {
        setError(data.error_code || "OCR processing failed.");
        return;
      }
      if (TERMINAL_OCR_STATUSES.has(data.ocr_status || data.status)) {
        await loadResult(id);
        return;
      }
      window.setTimeout(() => { void pollStatus(id); }, 1000);
    } catch (pollError) {
      if (alive.current) setError(pollError.message || "Unable to monitor OCR processing.");
    }
  };

  const handleUpload = async event => {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    setResult(null);
    setReviewedPages([]);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await apiFetch("/api/ocr/documents", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, "Unable to upload the document."));
      if (!alive.current) return;
      setDocumentId(data.document_id);
      setStatus(data);
      setFile(null);
      setNotice("Document uploaded. OCR processing is in progress.");
      void pollStatus(data.document_id);
    } catch (uploadError) {
      if (alive.current) setError(uploadError.message || "Unable to upload the document.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const updatePage = (pageNumber, text) => {
    setReviewedPages(pages => pages.map(page => (
      page.page_number === pageNumber ? { ...page, text } : page
    )));
  };

  const handleIndex = async event => {
    event.preventDefault();
    if (!documentId || !reviewedPages.length || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`/api/ocr/documents/${encodeURIComponent(documentId)}/index`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_confirmed: true,
          case_no: null,
          reviewed_pages: reviewedPages,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, "Unable to index the reviewed document."));
      if (!alive.current) return;
      setStatus(data);
      setNotice("The reviewed OCR document was indexed for your account.");
    } catch (indexError) {
      if (alive.current) setError(indexError.message || "Unable to index the reviewed document.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  return (
    <div className="ocr-workflow-backdrop" role="presentation">
      <section className="ocr-workflow" role="dialog" aria-modal="true" aria-labelledby="ocr-workflow-title">
        <header className="ocr-workflow-header">
          <div><FileText size={20} aria-hidden="true" /><h2 id="ocr-workflow-title">OCR document</h2></div>
          <button type="button" className="ocr-close" onClick={onClose} aria-label="Close OCR document workflow"><X size={18} /></button>
        </header>

        <div className="ocr-workflow-body">
          <form className="ocr-upload-form" onSubmit={handleUpload}>
            <label htmlFor="ocr-file">Upload a scanned PDF or image</label>
            <input id="ocr-file" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" onChange={event => setFile(event.target.files?.[0] || null)} />
            <button type="submit" disabled={!file || busy}><Upload size={16} />{busy ? "Working..." : "Upload and process"}</button>
          </form>

          {status && <p className="ocr-status" role="status">Status: {status.status || status.ocr_status || "queued"}{status.index_status ? ` · Index: ${status.index_status}` : ""}</p>}
          {notice && <p className="ocr-notice" role="status">{notice}</p>}
          {error && <p className="ocr-error" role="alert">{error}</p>}

          {result && reviewedPages.length > 0 && (
            <form className="ocr-review-form" onSubmit={handleIndex}>
              <h3>Review extracted text</h3>
              <p className="ocr-help">Check each page before indexing. The current backend keeps OCR documents owner-private; case-linked indexing is unavailable until case authorization is configured.</p>
              <label htmlFor="ocr-case">Case assignment</label>
              <select id="ocr-case" value="" disabled><option value="">Unassigned (required currently)</option></select>
              {reviewedPages.map(page => (
                <label className="ocr-page-review" key={page.page_number} htmlFor={`ocr-page-${page.page_number}`}>
                  Page {page.page_number}
                  <textarea id={`ocr-page-${page.page_number}`} value={page.text} onChange={event => updatePage(page.page_number, event.target.value)} rows={5} />
                </label>
              ))}
              <button type="submit" disabled={busy}><FileText size={16} />Confirm review and index</button>
            </form>
          )}
        </div>
      </section>
    </div>
  );
}
