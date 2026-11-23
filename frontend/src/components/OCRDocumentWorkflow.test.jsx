import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OCRDocumentWorkflow from "./OCRDocumentWorkflow";
import { apiFetch } from "../api";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));

const response = (data, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => data,
});

beforeEach(() => {
  vi.mocked(apiFetch).mockReset(); sessionStorage.clear();
  Range.prototype.getBoundingClientRect = () => ({top:0,left:0,right:0,bottom:0,width:0,height:0});
  Range.prototype.getClientRects = () => [];
});
async function editContent(element, value) {
  await act(async () => { element.textContent = value; await new Promise(resolve => setTimeout(resolve, 0)); });
}

describe("OCR document workflow", () => {
  it("uploads, reviews and indexes OCR text without sending an owner ID", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path, options = {}) => {
      if (typeof path !== "string") return response({});
      if (path === "/api/ocr/documents" && options.method === "POST") {
        return response({ document_id: "a".repeat(64), status: "completed", ocr_status: "completed" });
      }
      if (path.endsWith("/status")) {
        return response({ document_id: "a".repeat(64), status: "completed", ocr_status: "completed" });
      }
      if (path === `/api/ocr/documents/${"a".repeat(64)}`) {
        return response({ pages: [{ page_number: 1, text: "Extracted evidence" }] });
      }
      if (path.endsWith("/index")) return response({ index_status: "indexed" });
      throw new Error(`Unexpected API call: ${path}`);
    });

    const user = userEvent.setup();
    render(<StrictMode><OCRDocumentWorkflow onClose={vi.fn()} /></StrictMode>);
    const file = new File(["%PDF-1.7"], "evidence.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Upload a scanned PDF or image"), file);
    await user.click(screen.getByRole("button", { name: "Upload and process" }));

    expect(await screen.findByText("Extracted evidence")).toBeVisible();
    expect(screen.getByText("Text extraction is complete. Review the text below before indexing.")).toBeVisible();
    expect(screen.queryByText("Document uploaded. OCR processing is in progress.")).not.toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/api/ocr/documents", expect.objectContaining({ method: "POST" }));
    const uploadOptions = vi.mocked(apiFetch).mock.calls[0][1];
    expect(uploadOptions.body).toBeInstanceOf(FormData);
    expect(uploadOptions.body.get("owner_user_id")).toBeNull();

    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Confirm review and index" }));
    const indexCall = vi.mocked(apiFetch).mock.calls.find(([path]) => typeof path === "string" && path.endsWith("/index"));
    expect(indexCall[1].body).toContain('"case_no":null');
    expect(await screen.findByText("Document saved successfully. Your reviewed content is ready for chatbot questions.")).toBeVisible();
  });
});

const docId = "b".repeat(64);
function completedMock(blocks, saveStatus = 200) {
  vi.mocked(apiFetch).mockImplementation(async (path, options={}) => {
    if (path === "/api/ocr/documents") return response({document_id:docId,status:"queued"});
    if (path.endsWith("/status")) return response({status:"completed",ocr_status:"completed",index_status:"not_indexed"});
    if (path.endsWith("/index")) return response(saveStatus === 200 ? {index_status:"indexed"} : {detail:"Indexing service unavailable. Please retry."}, saveStatus);
    return response({pages:[{page_number:1,text:"Original text",blocks}]});
  });
}
async function uploadImage(user) {
  await user.upload(screen.getByLabelText("Upload a scanned PDF or image"),new File(["image"],"form.png",{type:"image/png"}));
  await user.click(screen.getByRole("button",{name:"Upload and process"}));
}

it("saves table cell and form field corrections in the review payload", async () => {
  completedMock([{type:"table",rows:[["Item","Amount"],["Travel","500"]]},{type:"form",fields:[{label:"Name",value:"Karma"}]}]);
  const user=userEvent.setup(); render(<OCRDocumentWorkflow onClose={vi.fn()}/>);
  await uploadImage(user);
  const amount=await screen.findByText("500");
  await editContent(amount,"750");
  const name=screen.getByText("Karma");
  await editContent(name,"Pema");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button",{name:"Confirm review and index"}));
  const call=vi.mocked(apiFetch).mock.calls.find(([p])=>p.endsWith("/index"));
  const page=JSON.parse(call[1].body).reviewed_pages[0];
  expect(page.blocks[0].rows[1][1]).toBe("750");expect(page.blocks[1].fields[0].value).toBe("Pema");
  expect(await screen.findByText(/Document saved successfully/)).toBeVisible();
});

it("requires confirmation during extraction and opens a fresh upload after closing", async () => {
  vi.mocked(apiFetch).mockImplementation(async path => response(path.endsWith("/status") ? {status:"processing"} : {document_id:docId,status:"queued"}));
  const close=vi.fn(),user=userEvent.setup();const view=render(<StrictMode><OCRDocumentWorkflow onClose={close}/></StrictMode>);
  await uploadImage(user);
  await user.click(screen.getByLabelText("Close OCR document workflow"));
  expect(screen.getByRole("alertdialog")).toBeVisible();expect(close).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button",{name:"Keep reviewing"}));expect(close).not.toHaveBeenCalled();
  await user.click(screen.getByLabelText("Close OCR document workflow"));await user.click(screen.getByRole("button",{name:"Close window"}));expect(close).toHaveBeenCalledOnce();
  view.unmount();vi.mocked(apiFetch).mockClear();
  sessionStorage.setItem("acc-ocr-current-document",docId);
  render(<StrictMode><OCRDocumentWorkflow onClose={vi.fn()}/></StrictMode>);
  expect(screen.getByLabelText("Upload a scanned PDF or image")).toHaveValue("");
  expect(screen.queryByRole("textbox",{name:"Document review editor"})).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Document status")).not.toBeInTheDocument();
  expect(apiFetch).not.toHaveBeenCalled();
  expect(sessionStorage.getItem("acc-ocr-current-document")).toBeNull();
});

it("shows indexing failure and keeps reviewed cells editable for retry", async () => {
  completedMock([{type:"text",text:"Review retained"}],503);
  const user=userEvent.setup();render(<OCRDocumentWorkflow onClose={vi.fn()}/>);await uploadImage(user);
  await screen.findByText("Review retained");await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button",{name:"Confirm review and index"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Indexing service unavailable");
  expect(screen.getByRole("textbox",{name:"Document review editor"})).toHaveAttribute("contenteditable","true");expect(screen.queryByText(/Document saved successfully/)).not.toBeInTheDocument();
});

it("shows extraction failure rather than continuing progress forever", async () => {
  vi.mocked(apiFetch).mockImplementation(async path=>response(path.endsWith("/status") ? {status:"failed",error_code:"processing_failed"} : {document_id:docId,status:"queued"}));
  const user=userEvent.setup();render(<OCRDocumentWorkflow onClose={vi.fn()}/>);await uploadImage(user);
  expect(await screen.findByRole("alert")).toHaveTextContent("Text extraction failed");
  expect(screen.queryByText(/Extracting text and detecting/)).not.toBeInTheDocument();
});

it("opens an already indexed upload in editable Review and saves only on confirmation", async () => {
  let finishSave;
  vi.mocked(apiFetch).mockImplementation(async (path, options={}) => {
    if (path === "/api/ocr/documents") return response({document_id:docId,status:"completed",index_status:"indexed",duplicate:true});
    if (path.endsWith("/status")) return response({status:"completed",ocr_status:"completed",index_status:"indexed"});
    if (path.endsWith("/index")) return new Promise(resolve => {finishSave=resolve;});
    return response({pages:[{page_number:1,text:"Original",blocks:[{type:"table",rows:[["Item","Amount"],["Travel","500"]]},{type:"form",fields:[{label:"Name",value:"Karma"}]}]}]});
  });
  const user=userEvent.setup();render(<StrictMode><OCRDocumentWorkflow onClose={vi.fn()}/></StrictMode>);
  await uploadImage(user);
  const cell=await screen.findByText("500");
  const field=screen.getByText("Name");
  const editor=screen.getByRole("textbox",{name:"Document review editor"});
  const currentStep=()=>screen.getByLabelText("Document progress").querySelector('[aria-current="step"]');
  expect(currentStep()).toHaveTextContent("Review");expect(editor).toHaveAttribute("contenteditable","true");
  expect(vi.mocked(apiFetch).mock.calls.some(([path])=>path.endsWith("/index"))).toBe(false);
  await editContent(cell,"850");
  await editContent(field,"Name revised");
  expect(currentStep()).toHaveTextContent("Review");
  expect(vi.mocked(apiFetch).mock.calls.some(([path])=>path.endsWith("/index"))).toBe(false);
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button",{name:"Confirm review and index"}));
  expect(currentStep()).toHaveTextContent("Save for chat");expect(editor).toHaveAttribute("contenteditable","false");
  const savedCall=vi.mocked(apiFetch).mock.calls.find(([path])=>path.endsWith("/index"));
  expect(JSON.parse(savedCall[1].body).reviewed_pages[0].blocks[0].rows[1][1]).toBe("850");
  finishSave(response({index_status:"indexed"}));
  expect(await screen.findByText(/Document saved successfully/)).toBeVisible();
  expect(currentStep()).toHaveTextContent("Saved");
  expect(screen.getByRole("heading",{name:"Successfully saved and indexed"})).toBeVisible();
  expect(screen.queryByRole("textbox",{name:"Document review editor"})).not.toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"Upload another"}));
  expect(currentStep()).toHaveTextContent("Upload");
  expect(screen.queryByLabelText("Document status")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Upload a scanned PDF or image")).toHaveValue("");
  expect(screen.getByRole("button",{name:"Upload and process"})).toBeDisabled();
});


it("shows status and page count and requires agreement before saving optional case metadata",async()=>{
  completedMock([{type:"text",text:"Reviewed document"}]);
  const user=userEvent.setup();render(<OCRDocumentWorkflow onClose={vi.fn()}/>);await uploadImage(user);
  await screen.findByText("Reviewed document");
  const summary=screen.getByLabelText("Document status");
  expect(summary).toHaveTextContent("OCR status:completed");
  expect(summary).toHaveTextContent("Index status:not_indexed");
  expect(summary).toHaveTextContent("Pages:1");
  const save=screen.getByRole("button",{name:"Confirm review and index"});
  expect(save).toBeDisabled();
  await user.type(screen.getByLabelText("Case number (optional metadata)"),"ACC/2026/014");
  expect(save).toBeDisabled();
  await user.click(screen.getByRole("checkbox"));expect(save).toBeEnabled();
  await user.click(save);
  const call=vi.mocked(apiFetch).mock.calls.find(([p])=>p.endsWith("/index"));
  expect(JSON.parse(call[1].body)).toMatchObject({review_confirmed:true,case_number:"ACC/2026/014",case_no:null});
  await screen.findByText(/Document saved successfully/);
  expect(summary).toHaveTextContent("Index status:indexed");
  expect(summary).toHaveTextContent("Pages:1");
});


it("does not restore an abandoned review when the upload popup is opened again",async()=>{
  completedMock([{type:"text",text:"Abandoned document"}]);
  const user=userEvent.setup(),close=vi.fn();const view=render(<OCRDocumentWorkflow onClose={close}/>);
  await uploadImage(user);await screen.findByText("Abandoned document");
  await user.type(screen.getByLabelText("Case number (optional metadata)"),"OLD-CASE");
  await user.click(screen.getByLabelText("Close OCR document workflow"));
  await user.click(screen.getByRole("button",{name:"Close window"}));expect(close).toHaveBeenCalledOnce();
  view.unmount();vi.mocked(apiFetch).mockClear();
  render(<OCRDocumentWorkflow onClose={vi.fn()}/>);
  expect(screen.queryByText("Abandoned document")).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("OLD-CASE")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Document status")).not.toBeInTheDocument();
  expect(apiFetch).not.toHaveBeenCalled();
});

it("ignores a late upload response after closing and does not poll it in the next popup",async()=>{
  let finishUpload;
  vi.mocked(apiFetch).mockImplementation(()=>new Promise(resolve=>{finishUpload=resolve;}));
  const user=userEvent.setup(),close=vi.fn();const view=render(<OCRDocumentWorkflow onClose={close}/>);
  await uploadImage(user);await user.click(screen.getByLabelText("Close OCR document workflow"));
  await user.click(screen.getByRole("button",{name:"Close window"}));view.unmount();
  await act(async()=>{finishUpload(response({document_id:docId,status:"queued"}));});
  vi.mocked(apiFetch).mockClear();render(<OCRDocumentWorkflow onClose={vi.fn()}/>);
  expect(apiFetch).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Document status")).not.toBeInTheDocument();
});

it("shows confidence and evaluates a reference without changing the review", async () => {
  const snapshot={pages:[{page_number:1,text:"Original text",confidence:82.4,extraction_method:"paddleocr",preprocessing:{enabled:true,selection:"preprocessed"}}],average_confidence:82.4};
  vi.mocked(apiFetch).mockImplementation(async (path,options={})=>{
    if(path==="/api/ocr/documents")return response({document_id:docId,status:"queued"});
    if(path.endsWith("/status"))return response({status:"completed",ocr_status:"completed"});
    if(path.endsWith("/evaluate"))return response({cer_percent:12.5,wer_percent:50});
    return response(snapshot);
  });
  const user=userEvent.setup();render(<OCRDocumentWorkflow onClose={vi.fn()}/>);await uploadImage(user);
  expect(await screen.findByText("OCR model confidence: 82.4%")).toBeVisible();
  await user.click(screen.getByText("Page confidence and preprocessing"));
  expect(screen.getByText(/Confidence 82.4% · Preprocessing enabled/)).toBeVisible();
  await user.click(screen.getByText("Evaluate against correct reference text (optional)"));
  await user.type(screen.getByLabelText("Correct reference transcription"),"Correct text");
  await user.click(screen.getByRole("button",{name:"Calculate error rates"}));
  expect(await screen.findByText("Character error rate (CER): 12.5%")).toBeVisible();
  expect(screen.getByText("Word error rate (WER): 50%")).toBeVisible();
  expect(screen.getByRole("textbox",{name:"Document review editor"})).toHaveTextContent("Original text");
  expect(apiFetch).toHaveBeenCalledWith(`/api/ocr/documents/${docId}/evaluate`,expect.objectContaining({body:JSON.stringify({page_number:1,reference_text:"Correct text"})}));
  await user.type(screen.getByLabelText("Correct reference transcription")," changed");
  expect(screen.queryByText("Character error rate (CER): 12.5%")).not.toBeInTheDocument();
});

it("shows direct PDF extraction without inventing an OCR score",async()=>{
  completedMock([{type:"text",text:"Original text"}]);
  const original=vi.mocked(apiFetch).getMockImplementation();
  vi.mocked(apiFetch).mockImplementation(async(path,options)=>path===`/api/ocr/documents/${docId}` ? response({pages:[{page_number:1,text:"Direct evidence",extraction_method:"direct"}],average_confidence:null}) : original(path,options));
  const user=userEvent.setup();render(<OCRDocumentWorkflow onClose={vi.fn()}/>);await uploadImage(user);
  expect(await screen.findByText("Text extracted directly from the PDF. OCR confidence does not apply.")).toBeVisible();
  expect(screen.queryByText(/OCR model confidence:/)).not.toBeInTheDocument();
});
