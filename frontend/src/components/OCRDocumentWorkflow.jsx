import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { FileText, Upload, X } from "lucide-react";
import OCRExtractionQuality from "./OCRExtractionQuality";
import OCRDocumentEditor from "./OCRDocumentEditor";
import { textBlock } from "./ocrEditorDocument";
import "./ocr-document-workflow.css";

const TERMINAL = new Set(["completed", "not_required", "manual_review", "failed"]);
function errorMessage(data, fallback) {
  return typeof data?.detail === "string" ? data.detail : fallback;
}

export default function OCRDocumentWorkflow({ onClose }) {
  const [file,setFile] = useState(null);
  const [documentId,setDocumentId] = useState("");
  const [status,setStatus] = useState(null);
  const [pages,setPages] = useState([]);
  const [averageConfidence,setAverageConfidence] = useState(null);
  const [busy,setBusy] = useState(false);
  const [processing,setProcessing] = useState(false);
  const [saving,setSaving] = useState(false);
  const [saved,setSaved] = useState(false);
  const [reviewConfirmed,setReviewConfirmed] = useState(false);
  const [caseNumber,setCaseNumber] = useState("");
  const [editorVersion,setEditorVersion] = useState(0);
  const [confirmReextract,setConfirmReextract] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const [confirmClose,setConfirmClose] = useState(false);
  const alive = useRef(false);
  const timer = useRef(null);
  const fileInput = useRef(null);
  const dialog = useRef(null);
  const generation = useRef(0);
  const processingActive = busy || processing;

  useEffect(() => {
    alive.current = true;
    // Clear legacy resume state. Each popup now starts a new upload.
    sessionStorage.removeItem("acc-ocr-current-document");
    return () => { alive.current = false; generation.current++; clearTimeout(timer.current); };
  }, []);

  useEffect(() => {
    if (!processingActive && (!pages.length || saved)) return;
    const warn = event => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload",warn);
    return () => window.removeEventListener("beforeunload",warn);
  }, [processingActive, pages.length, saved]);

  const current = run => alive.current && generation.current === run;
  async function pollStatus(id, run) {
    try {
      const response = await apiFetch(`/api/ocr/documents/${encodeURIComponent(id)}/status`, {background:true});
      const data = await response.json();
      if (!response.ok) {
        throw new Error(errorMessage(data,"Unable to check extraction. Please upload the original again to retry."));
      }
      if (!current(run)) return;
      setStatus(data);
      setCaseNumber(data.case_number || "");
      if (data.status === "failed") throw new Error("Text extraction failed. Please upload the document again to retry.");
      if (!TERMINAL.has(data.ocr_status || data.status)) {
        timer.current = window.setTimeout(() => { void pollStatus(id,run); },1000);
        return;
      }
      const resultResponse = await apiFetch(`/api/ocr/documents/${encodeURIComponent(id)}`);
      const result = await resultResponse.json();
      if (!resultResponse.ok) throw new Error(errorMessage(result,"Unable to load extracted text. Please upload the original again to retry."));
      if (!current(run)) return;
      setAverageConfidence(result.average_confidence ?? null);
      setPages((result.pages || []).map(p => ({...p, blocks:p.blocks?.length ? p.blocks : [textBlock(p.text || "")]})));
      setProcessing(false);
      setEditorVersion(v=>v+1);
      setSaved(false);setReviewConfirmed(false);
      if (data.index_status === "indexed") {
        setNotice("This document was previously saved. Review and edit it below, then confirm to save your changes.");
      } else setNotice("Text extraction is complete. Review the text below before indexing.");
    } catch (e) { if (current(run)) { setError(e.message); setNotice(""); setProcessing(false); } }
  }

  async function handleUpload(event) {
    event.preventDefault();
    if (!file || processingActive) return;
    const run = ++generation.current;
    clearTimeout(timer.current);
    setSaved(false);setReviewConfirmed(false);setCaseNumber("");
    setBusy(true); setError(""); setNotice("Uploading document…"); setPages([]); setStatus(null);
    try {
      const body = new FormData(); body.append("file",file);
      const response = await apiFetch("/api/ocr/documents",{method:"POST",body});
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data,"Upload failed. Please try again."));
      if (!current(run)) return;
      setDocumentId(data.document_id); setStatus(data); setFile(null); setProcessing(true);
      if (fileInput.current) fileInput.current.value = "";
      setNotice("Extracting text and detecting tables and forms. Keep this window open to review the result.");
      void pollStatus(data.document_id,run);
    } catch (e) { if (current(run)) {setError(e.message);setNotice("");} }
    finally { if (current(run)) setBusy(false); }
  }

  async function handleIndex(event) {
    event.preventDefault();
    if (!documentId || !pages.length || processingActive || saved || !reviewConfirmed) return;
    setSaving(true);setBusy(true);setError("");setNotice("Saving reviewed content and preparing it for chatbot questions…");
    try {
      const response = await apiFetch(`/api/ocr/documents/${encodeURIComponent(documentId)}/index`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({review_confirmed:reviewConfirmed,case_no:null,case_number:caseNumber.trim() || null,reviewed_pages:pages.map(p => ({page_number:p.page_number,text:p.text || "",blocks:p.blocks,editor_json:p.editor_json}))}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data,"Saving or indexing failed. Your extracted text is retained; try saving again."));
      if (!alive.current) return;
      setStatus(previous => ({...previous,...data}));setSaved(true);
      setNotice("Document saved successfully. Your reviewed content is ready for chatbot questions.");
    } catch (e) { if (alive.current) {setError(e.message);setNotice("");} }
    finally { if (alive.current) { setBusy(false); setSaving(false); } }
  }

  async function reextract() {
    setConfirmReextract(false);
    const run=++generation.current;
    clearTimeout(timer.current);setBusy(true);setSaved(false);setReviewConfirmed(false);setError("");setNotice("Re-extracting the original document with current layout detection…");
    try {
      const response=await apiFetch(`/api/ocr/documents/${encodeURIComponent(documentId)}/reprocess`,{method:"POST"});
      const data=await response.json();
      if(!response.ok) throw new Error(errorMessage(data,"Re-extraction failed. Please try again."));
      if(!current(run)) return;
      setPages([]);setStatus(data);setProcessing(true);void pollStatus(documentId,run);
    } catch(e) {if(current(run)){setError(e.message);setNotice("");}}
    finally {if(current(run))setBusy(false);}
  }

  function startFresh() {
    generation.current++;
    clearTimeout(timer.current);
    setFile(null);setDocumentId("");setStatus(null);setPages([]);
    setBusy(false);setProcessing(false);setSaving(false);setSaved(false);
    setReviewConfirmed(false);setCaseNumber("");setError("");setNotice("");
    setConfirmClose(false);setConfirmReextract(false);setEditorVersion(v=>v+1);
    if(fileInput.current) fileInput.current.value="";
    if(dialog.current) dialog.current.scrollTop=0;
  }

  function closeWindow() {
    generation.current++;
    clearTimeout(timer.current);
    alive.current=false;
    onClose();
  }

  useEffect(()=>{ if(!saved) fileInput.current?.focus(); },[saved]);

  const phase = saved || saving ? 4 : pages.length ? 3 : processing ? 2 : 1;
  const requestClose = () => processingActive || (pages.length > 0 && !saved) ? setConfirmClose(true) : closeWindow();
  return <div className="ocr-workflow-backdrop" role="presentation"><section ref={dialog} className="ocr-workflow" role="dialog" aria-modal="true" aria-labelledby="ocr-workflow-title" onKeyDown={e => {if(e.key === "Escape") requestClose();}}>
    <header className="ocr-workflow-header"><div><FileText size={20}/><h2 id="ocr-workflow-title">Upload and review document</h2></div><button type="button" className="ocr-close" onClick={requestClose} aria-label="Close OCR document workflow"><X size={18}/></button></header>
    <div className="ocr-workflow-body">
      <ol className="ocr-steps" aria-label="Document progress">{["Upload","Extract","Review","Save for chat"].map((label,i) => <li key={label} className={phase > i+1 ? "is-complete" : phase === i+1 ? "is-current" : "is-upcoming"} aria-current={phase === i+1 ? "step" : undefined}><span className="ocr-step-marker" aria-hidden="true">{i+1}</span><span className="ocr-step-label">{label}</span><span className="ocr-step-state">{phase > i+1 ? "Complete" : phase === i+1 ? (saved ? "Saved" : "Current step") : "Upcoming"}</span></li>)}</ol>
      {!saved && <form className="ocr-upload-form" onSubmit={handleUpload}><label htmlFor="ocr-file">Upload a PDF or image</label><input ref={fileInput} id="ocr-file" aria-label="Upload a scanned PDF or image" type="file" accept=".pdf,.png,.jpg,.jpeg" disabled={processingActive} onChange={e => setFile(e.target.files?.[0] || null)}/><small>PDF, PNG or JPEG · up to 25 MB. Digital PDFs and scanned documents are supported.</small><button type="submit" disabled={!file || processingActive}><Upload size={16}/>{processingActive ? "Working…" : "Upload and process"}</button></form>}
      {status && <dl className="ocr-status-summary" aria-label="Document status"><div><dt>OCR status:</dt><dd>{status.ocr_status || status.status || "queued"}</dd></div><div><dt>Index status:</dt><dd>{saving ? "indexing" : status.index_status || "not_indexed"}</dd></div><div><dt>Pages:</dt><dd>{status.page_count ?? (pages.length || "—")}</dd></div></dl>}
      {!saved && notice && <p className="ocr-notice" role="status">{notice}</p>}{error && <p className="ocr-error" role="alert">{error}</p>}
      {saved && <section className="ocr-success" role="status" aria-labelledby="ocr-success-title"><h3 id="ocr-success-title">Successfully saved and indexed</h3><p>{notice}</p>{caseNumber && <p><strong>Case number:</strong> {caseNumber}</p>}<div className="ocr-actions"><button type="button" className="ocr-secondary-button" onClick={closeWindow}>Close</button><button type="button" className="ocr-primary-button" onClick={startFresh}><Upload size={16}/>Upload another</button></div></section>}
      {!saved && pages.length > 0 && <OCRExtractionQuality key={`${documentId}-${editorVersion}`} documentId={documentId} pages={pages} averageConfidence={averageConfidence}/>}
      {!saved && pages.length > 0 && <form className="ocr-review-form" onSubmit={handleIndex} onKeyDown={e => { if (e.key === "Enter" && e.target.tagName === "INPUT") e.preventDefault(); }}><h3>Review extracted text</h3><p className="ocr-help">Edit your document below. Text, tables and form fields are in one document. Check recognition and layout before saving.</p>
        {pages.some(p=>p.extraction_method === "paddleocr") && <p className="ocr-help">Scanned handwriting may be misread. Verify names, dates and numbers against the original before indexing.</p>}
        <button type="button" disabled={processingActive} onClick={()=>setConfirmReextract(true)}>Re-extract original</button>
        <OCRDocumentEditor key={`${documentId}-${editorVersion}`} pages={pages} disabled={busy} onChange={updated => { setSaved(false); setReviewConfirmed(false); setNotice("You have unsaved review changes. Confirm review and index to save them."); setPages(updated); }}/>

        <div className="ocr-review-confirmation">
          <label htmlFor="ocr-case-number">Case number (optional metadata)</label>
          <input id="ocr-case-number" type="text" maxLength={64} placeholder="Optional" value={caseNumber} disabled={processingActive} onChange={e=>{setCaseNumber(e.target.value);setSaved(false);setReviewConfirmed(false);setNotice("You have unsaved review changes. Confirm review and index to save them.");}}/>
          <label className="ocr-review-agreement" htmlFor="ocr-review-agreement"><input id="ocr-review-agreement" type="checkbox" checked={reviewConfirmed} disabled={processingActive || saved} onChange={e=>setReviewConfirmed(e.target.checked)}/><span>I reviewed the extracted text and confirm it is appropriate to index.</span></label>
          <p className="ocr-help">The case number is descriptive metadata. Documents remain private to your account. Indexing starts only after you confirm.</p>
        </div>
        <button type="submit" disabled={processingActive || saved || !reviewConfirmed}><FileText size={16}/>{saved ? "Saved for chat" : busy ? "Saving…" : "Confirm review and index"}</button>
        {saved && <p>Try asking: What does “{status.filename || "your uploaded filename"}” say about your topic?</p>}
      </form>}
      {confirmReextract && <section className="ocr-close-confirmation" role="alertdialog" aria-labelledby="ocr-reextract-title"><h3 id="ocr-reextract-title">Re-extract the original?</h3><p>This replaces your current review with a new extraction. The document must be reviewed and saved again before chat can retrieve it.</p><div className="ocr-actions"><button type="button" className="ocr-secondary-button" onClick={()=>setConfirmReextract(false)}>Keep current review</button><button type="button" className="ocr-primary-button" onClick={reextract}>Re-extract now</button></div></section>}
      {confirmClose && <section className="ocr-close-confirmation" role="alertdialog" aria-labelledby="ocr-close-title"><h3 id="ocr-close-title">Close document review?</h3><p>{processingActive ? "Processing will continue in the background. Closing leaves this review; the next upload window will start fresh." : "Your review edits will be lost. The original extracted text is saved."}</p><div className="ocr-actions"><button type="button" className="ocr-primary-button" autoFocus onClick={() => setConfirmClose(false)}>Keep reviewing</button><button type="button" className="ocr-secondary-button" onClick={closeWindow}>Close window</button></div></section>}
    </div>
  </section></div>;
}
