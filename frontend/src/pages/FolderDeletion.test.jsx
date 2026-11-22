import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import Chat from "./Chat";
import FolderView from "./FolderView";
import { Sidebar } from "./Dashboard";
import { apiFetch } from "../api";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));
vi.mock("./Dashboard", () => ({ Sidebar: vi.fn(() => null) }));
vi.mock("./CDRNetwork", () => ({ default: () => null }));
vi.mock("./RelationshipNetwork", () => ({ default: () => null }));
let folders;
let failDelete;
const response = (data, status = 200) => ({ ok: status < 400, json: async () => data });
const latestSidebar = () => Sidebar.mock.calls.at(-1)[0];

beforeEach(() => {
  vi.clearAllMocks();
  folders = [{ id: "folder-1", name: "Case folder" }];
  failDelete = false;
  localStorage.setItem("accUser", JSON.stringify({ id: "alice" }));
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(window, "alert").mockImplementation(() => {});
  apiFetch.mockImplementation(async (path, options) => {
    if (options?.method === "DELETE") {
      if (failDelete) return response({ detail: "Database unavailable" }, 503);
      folders = [];
      return response({ success: true });
    }
    return response(path.startsWith("/api/folders") ? { folders } : { conversations: [] });
  });
});

function mount(path, page) {
  return render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/chat" element={page} />
    <Route path="/folders/:folderId" element={page} />
    <Route path="/Dashboard" element={<h1>Dashboard</h1>} />
  </Routes></MemoryRouter>);
}

it("persists folder deletion from chat and stays deleted after remount", async () => {
  const view = mount("/chat", <Chat />);
  await waitFor(() => expect(latestSidebar().folders).toHaveLength(1));
  await act(async () => latestSidebar().onDeleteFolder("folder-1"));
  expect(apiFetch).toHaveBeenCalledWith("/api/folders/folder-1", { method: "DELETE" });
  expect(latestSidebar().folders).toEqual([]);
  view.unmount();
  mount("/chat", <Chat />);
  await waitFor(() => expect(latestSidebar().folders).toEqual([]));
});

it("keeps the folder visible and reports backend deletion failures", async () => {
  failDelete = true;
  mount("/chat", <Chat />);
  await waitFor(() => expect(latestSidebar().folders).toHaveLength(1));
  await act(async () => latestSidebar().onDeleteFolder("folder-1"));
  expect(latestSidebar().folders).toHaveLength(1);
  expect(window.alert).toHaveBeenCalledWith("Database unavailable");
});

it("deletes the open folder from its page and returns to the dashboard", async () => {
  mount("/folders/folder-1", <FolderView />);
  await waitFor(() => expect(latestSidebar().folders).toHaveLength(1));
  await act(async () => latestSidebar().onDeleteFolder("folder-1"));
  expect(apiFetch).toHaveBeenCalledWith("/api/folders/folder-1", { method: "DELETE" });
  expect(screen.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});
