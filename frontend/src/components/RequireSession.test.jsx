import React from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RequireSession from "./RequireSession";
import { loadSession } from "../api";

vi.mock("../api", () => ({ loadSession: vi.fn() }));
beforeEach(() => { vi.mocked(loadSession).mockReset(); });

function renderProtectedPage() {
  return render(<MemoryRouter initialEntries={["/private"]}><Routes>
    <Route path="/login" element={<h1>Sign in</h1>} />
    <Route element={<RequireSession />}>
      <Route path="/private" element={<h1>Investigation workspace</h1>} />
    </Route>
  </Routes></MemoryRouter>);
}

describe("protected pages", () => {
  it("waits for server verification before exposing the workspace", async () => {
    let resolve;
    loadSession.mockImplementation(() => new Promise(done => { resolve = done; }));
    renderProtectedPage();
    expect(screen.getByRole("status")).toHaveTextContent("Checking your session");
    expect(screen.queryByText("Investigation workspace")).not.toBeInTheDocument();
    await act(async () => resolve({ id: "alice" }));
    expect(await screen.findByText("Investigation workspace")).toBeVisible();
  });
  it("redirects expired sessions to sign-in", async () => {
    loadSession.mockRejectedValue(Object.assign(new Error("Expired"), { status: 401 }));
    localStorage.setItem("accUser", '{"id":"alice"}');
    renderProtectedPage();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(localStorage.getItem("accUser")).toBeNull();
  });
  it("lets users retry a temporary backend failure", async () => {
    loadSession.mockRejectedValueOnce(new Error("Database unavailable")).mockResolvedValueOnce({ id: "alice" });
    renderProtectedPage();
    expect(await screen.findByText("Database unavailable")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Investigation workspace")).toBeVisible();
  });
  it("leaves the workspace when an API request reports session expiry", async () => {
    loadSession.mockResolvedValue({ id: "alice" });
    renderProtectedPage();
    await screen.findByText("Investigation workspace");
    act(() => window.dispatchEvent(new Event("acc-session-expired")));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});
