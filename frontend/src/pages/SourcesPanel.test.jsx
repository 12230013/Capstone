import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SourcesPanel from "./SourcesPanel";
import { apiFetch } from "../api";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));
const sources = [{ doc_id: "stmt_01", filename: "stmt_01.txt", case_no: "19/25-26", sentence_ids: ["stmt_01-s2"], excerpt: "Retrieved evidence passage" }];
beforeEach(() => { vi.mocked(apiFetch).mockReset(); });

describe("source document panel", () => {
  it("opens the actual backend document and highlights cited sentences", async () => {
    apiFetch.mockResolvedValue({ ok: true, json: async () => ({ text: "Original statement", sentences: [
      { id: "stmt_01-s1", text: "Other sentence" }, { id: "stmt_01-s2", text: "Cited sentence" },
    ] }) });
    render(<SourcesPanel sources={sources} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /stmt_01.txt/ }));
    expect(await screen.findByText("Original statement")).toBeVisible();
    expect(screen.getByText("Cited sentence").tagName).toBe("MARK");
    expect(screen.getByText("Other sentence").closest("mark")).toBeNull();
    expect(apiFetch.mock.calls[0][0]).toBe("/api/sources/stmt_01");
    await userEvent.click(screen.getByRole("button", { name: "Back to sources" }));
    expect(screen.getByRole("button", { name: /stmt_01.txt/ })).toBeVisible();
  });
  it("keeps the retrieved passage visible when the original file is missing", async () => {
    apiFetch.mockResolvedValue({ ok: false, json: async () => ({ detail: "Original file unavailable" }) });
    render(<SourcesPanel sources={sources} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /stmt_01.txt/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("Original file unavailable");
    expect(screen.getByText("Retrieved evidence passage")).toBeVisible();
  });
  it("closes with the header control or Escape", async () => {
    const close = vi.fn();
    render(<SourcesPanel sources={sources} onClose={close} />);
    await userEvent.click(screen.getByRole("button", { name: "Close sources" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalledTimes(2);
  });
  it("cancels document loading when the panel unmounts", async () => {
    apiFetch.mockReturnValue(new Promise(() => {}));
    const { unmount } = render(<SourcesPanel sources={sources} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /stmt_01.txt/ }));
    const signal = apiFetch.mock.calls[0][1].signal;
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
