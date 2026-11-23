import { useState } from "react";
import { apiFetch } from "../api";

const score = value => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}%` : "Unavailable";

export default function OCRExtractionQuality({documentId, pages, averageConfidence, averageLayoutConfidence, hardware, ocrModel, activeOcrModel, modelUpgradeAvailable}) {
  const [pageNumber, setPageNumber] = useState(pages[0].page_number);
  const [reference, setReference] = useState("");
  const [metrics, setMetrics] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ocrPages = pages.filter(p => p.extraction_method !== "direct");
  const isVL = pages.some(p=>p.extraction_method === "paddleocr_vl");
  async function evaluate(event) {
    event.preventDefault();setBusy(true);setMetrics(null);setError("");
    try {
      const response = await apiFetch(`/api/ocr/documents/${encodeURIComponent(documentId)}/evaluate`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({page_number:Number(pageNumber),reference_text:reference}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Unable to evaluate this page.");
      setMetrics(data);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  return <section className="ocr-extraction-quality" aria-label="Extraction quality">
    <h3>Extraction information</h3>
    {modelUpgradeAvailable && <p><strong>Current OCR model: {activeOcrModel}</strong></p>}
    {ocrModel && <p><strong>{modelUpgradeAvailable ? "Saved extraction model" : "OCR model"}: {ocrModel}</strong></p>}
    {hardware && <p className="ocr-help">Recognition: {hardware.recognition_device === "metal" ? "Apple Metal GPU (MLX)" : hardware.recognition_device?.startsWith("gpu") ? `NVIDIA CUDA GPU (${hardware.recognition_device})` : "CPU"} · Layout: {hardware.device}</p>}
    {isVL ? <><p><strong>Layout detection confidence: {score(averageLayoutConfidence)}</strong></p><p className="ocr-help">VL 1.6 does not return text-recognition confidence. This score measures detected document regions before review, not transcription accuracy or table correctness. Use reference-based CER/WER below to measure text errors.</p></> : ocrPages.length > 0 ? <><p><strong>OCR model confidence: {score(averageConfidence)}</strong></p><p className="ocr-help">Average recognition confidence before review. This is not measured accuracy and does not score table layout. Verify handwriting, names, dates and numbers.</p></> : <p>Text extracted directly from the PDF. OCR confidence does not apply.</p>}
    <details><summary>Page confidence and preprocessing</summary><ul>{pages.map(p => <li key={p.page_number}>Page {p.page_number}: {p.extraction_method === "direct" ? "Direct PDF text · OCR not used" : `${p.extraction_method === "paddleocr_vl" ? "Layout confidence " + score(p.layout_confidence) : "Confidence " + score(p.confidence)} · ${p.preprocessing?.selection === "original_rgb_fallback" ? "Preprocessing failed; original image used" : p.preprocessing?.enabled ? "Preprocessing enabled" : "Image cleanup not applied"}`}</li>)}</ul></details>
    <details><summary>Evaluate against correct reference text (optional)</summary>
      <p className="ocr-help">Paste an accurate transcription of the entire selected page in reading order. This compares the original extracted text with your reference, not your review edits. Spaces and line wrapping are normalized; case and punctuation count.</p>
      <form onSubmit={evaluate}>
        <label htmlFor="ocr-evaluation-page">Page to evaluate</label>
        <select id="ocr-evaluation-page" value={pageNumber} disabled={busy} onChange={e=>{setPageNumber(Number(e.target.value));setReference("");setMetrics(null);setError("");}}>{pages.map(p=><option key={p.page_number} value={p.page_number}>Page {p.page_number}</option>)}</select>
        <label htmlFor="ocr-reference-text">Correct reference transcription</label>
        <textarea id="ocr-reference-text" rows={5} maxLength={20000} value={reference} disabled={busy} onChange={e=>{setReference(e.target.value);setMetrics(null);}}/>
        <button type="submit" className="ocr-primary-button" disabled={busy || !reference.trim()}>{busy ? "Evaluating…" : "Calculate error rates"}</button>
      </form>
      {error && <p className="ocr-error" role="alert">{error}</p>}
      {metrics && <div role="status"><p><strong>Character error rate (CER): {metrics.cer_percent}%</strong></p><p><strong>Word error rate (WER): {metrics.wer_percent}%</strong></p><p className="ocr-help">Lower is better; 0% means an exact match after normalization. Insertions can make error rates exceed 100%. These scores depend on the correctness of your reference and do not measure table structure.</p></div>}
    </details>
  </section>;
}
