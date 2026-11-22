import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Chat from "./Chat";
import { apiFetch } from "../api";
import { Sidebar } from "./Dashboard";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));
vi.mock("./Dashboard", () => ({ Sidebar: vi.fn(() => null) }));
vi.mock("./CDRNetwork", () => ({ default: () => null }));
vi.mock("./RelationshipNetwork", () => ({ default: () => null }));
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(Sidebar).mockClear();
  localStorage.setItem("accUser", JSON.stringify({ id: "alice", name: "Test User" }));
  vi.spyOn(console, "error").mockImplementation(() => {});
});

function renderChat(chatResponse, initialState) {
  apiFetch.mockImplementation((path, options) => {
    if (path === "/api/chat") return chatResponse(options);
    if (path.startsWith("/api/folders")) return Promise.resolve(response({ folders: [] }));
    return Promise.resolve(response({ conversations: [] }));
  });
  render(<MemoryRouter initialEntries={[{ pathname: "/chat", state: initialState }]}><Routes>
    <Route path="/chat" element={<Chat />} />
    <Route path="/chat/:conversationId" element={<Chat />} />
  </Routes></MemoryRouter>);
}

describe("chat submissions", () => {
  it("passes initial folders and conversations to the sidebar without nesting", () => {
    const state = {
      folders: [{ id: "folder-1", name: "Case folder" }],
      conversations: [{ id: "conversation-1", title: "Existing conversation" }],
    };
    renderChat(async () => response({}), state);
    const props = vi.mocked(Sidebar).mock.calls[0][0];
    expect(props.folders).toEqual(state.folders);
    expect(props.conversations).toEqual(state.conversations);
  });
  it("restores failed questions and retries without duplicate bubbles", async () => {
    const bodies = [];
    let attempt = 0;
    renderChat(async options => {
      bodies.push(JSON.parse(options.body));
      attempt += 1;
      return attempt === 1 ? response({ detail: "Model unavailable" }, 503)
        : response({ conversation_id: "conversation-1", response: { answer: "Supported answer", sources: [] } });
    });
    const user = userEvent.setup();
    const input = screen.getByRole("textbox", { name: "Ask the ACC assistant" });
    await user.type(input, "Tell me about the Haa case");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Model unavailable");
    expect(input).toHaveValue("Tell me about the Haa case");
    expect(screen.queryByText("Tell me about the Haa case")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Supported answer")).toBeVisible();
    expect(screen.getAllByText("Tell me about the Haa case")).toHaveLength(1);
    expect(bodies[1].request_id).toBe(bodies[0].request_id);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("prevents repeated submissions while an answer is pending", async () => {
    const submit = vi.fn(() => new Promise(() => {}));
    renderChat(submit);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "Ask the ACC assistant" }), "Summarize the case");
    await user.dblClick(screen.getByRole("button", { name: "Send message" }));
    expect(submit).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("opens the source list for an assistant answer", async () => {
    renderChat(async () => response({ conversation_id: "conversation-1", response: {
      answer: "Supported answer", sources: [{ doc_id: "stmt_01", filename: "stmt_01.txt", excerpt: "Evidence" }],
    } }));
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "Ask the ACC assistant" }), "Summarize the statement");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    await user.click(await screen.findByRole("button", { name: "View 1 sources" }));
    expect(screen.getByRole("complementary", { name: "Sources" })).toBeVisible();
    expect(screen.getByRole("button", { name: /stmt_01.txt/ })).toBeVisible();
  });
});
