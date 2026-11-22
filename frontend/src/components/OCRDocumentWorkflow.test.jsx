import { render, screen } from "@testing-library/react";
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

beforeEach(() => vi.mocked(apiFetch).mockReset());

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
    render(<OCRDocumentWorkflow onClose={vi.fn()} />);
    const file = new File(["%PDF-1.7"], "evidence.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Upload a scanned PDF or image"), file);
    await user.click(screen.getByRole("button", { name: "Upload and process" }));

    expect(await screen.findByDisplayValue("Extracted evidence")).toBeVisible();
    expect(apiFetch).toHaveBeenCalledWith("/api/ocr/documents", expect.objectContaining({ method: "POST" }));
    const uploadOptions = vi.mocked(apiFetch).mock.calls[0][1];
    expect(uploadOptions.body).toBeInstanceOf(FormData);
    expect(uploadOptions.body.get("owner_user_id")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Confirm review and index" }));
    const indexCall = vi.mocked(apiFetch).mock.calls.find(([path]) => typeof path === "string" && path.endsWith("/index"));
    expect(indexCall[1].body).toContain('"case_no":null');
    expect(await screen.findByText("The reviewed OCR document was indexed for your account.")).toBeVisible();
  });
});
