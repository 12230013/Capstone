import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Login from "./Login";
import Signup from "./Signup";
import { apiFetch, setCsrfToken } from "../api";

vi.mock("../api", () => ({ apiFetch: vi.fn(), setCsrfToken: vi.fn() }));
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
beforeEach(() => { vi.mocked(apiFetch).mockReset(); vi.mocked(setCsrfToken).mockReset(); vi.spyOn(console, "error").mockImplementation(() => {}); });

function renderAuth(page) {
  return render(<MemoryRouter initialEntries={["/auth"]}><Routes>
    <Route path="/auth" element={page} />
    <Route path="/dashboard" element={<h1>Dashboard</h1>} />
    <Route path="/login" element={<h1>Login destination</h1>} />
  </Routes></MemoryRouter>);
}

async function fillLogin(user) {
  await user.type(screen.getByLabelText("EMAIL"), "staff@example.com");
  await user.type(screen.getByLabelText("PASSWORD"), "Password1!");
}

function fillSignup() {
  for (const [label, value] of [
    ["NAME", "Test User"], ["EMPLOYEE ID", "ACC-1"], ["EMAIL", "staff@example.com"],
    ["DEPARTMENT", "Investigations"], ["PASSWORD", "Password1!"],
  ]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.change(screen.getByLabelText("ROLE"), { target: { value: "Investigator" } });
}

describe("sign-in form", () => {
  it("shows a failed login clearly and allows another submission", async () => {
    apiFetch.mockResolvedValueOnce(response({ detail: "Invalid email or password" }, 401))
      .mockResolvedValueOnce(response({ user: { id: "alice", name: "Test User" }, csrf_token: "csrf" }));
    const user = userEvent.setup();
    renderAuth(<Login />);
    await fillLogin(user);
    await user.click(screen.getByRole("button", { name: "Sign In" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(screen.getByRole("alert")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Sign In" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeVisible();
    expect(setCsrfToken).toHaveBeenCalledWith("csrf");
    expect(JSON.parse(localStorage.getItem("accUser"))).toMatchObject({ id: "alice" });
    expect(localStorage.getItem("accSessionToken")).toBeNull();
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ email: "staff@example.com", password: "Password1!" });
  });

  it("disables submission while login is pending", async () => {
    apiFetch.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderAuth(<Login />);
    await fillLogin(user);
    await user.click(screen.getByRole("button", { name: "Sign In" }));
    expect(screen.getByRole("button", { name: "Signing In..." })).toBeDisabled();
    expect(apiFetch).toHaveBeenCalledOnce();
  });
});

describe("sign-up form", () => {
  it("shows readable backend validation errors", async () => {
    apiFetch.mockResolvedValue(response({ detail: [{ loc: ["body", "employee_id"], msg: "Invalid employee ID" }] }, 422));
    renderAuth(<Signup />);
    fillSignup();
    fireEvent.submit(screen.getByRole("button", { name: "Sign Up" }).closest("form"));
    expect(await screen.findByRole("alert")).toHaveTextContent("employee id: Invalid employee ID");
  });

  it("clears old errors when the user edits a field", async () => {
    apiFetch.mockResolvedValue(response({ detail: "Email is already registered" }, 400));
    renderAuth(<Signup />);
    fillSignup();
    fireEvent.submit(screen.getByRole("button", { name: "Sign Up" }).closest("form"));
    await screen.findByRole("alert");
    fireEvent.change(screen.getByLabelText("EMAIL"), { target: { value: "another@example.com" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("redirects to login after successful registration", async () => {
    vi.useFakeTimers();
    apiFetch.mockResolvedValue(response({ message: "User created successfully", user_id: "alice" }));
    renderAuth(<Signup />);
    fillSignup();
    await act(async () => fireEvent.submit(screen.getByRole("button", { name: "Sign Up" }).closest("form")));
    expect(screen.getByText("Account created successfully! Redirecting to login...")).toBeVisible();
    await act(async () => vi.advanceTimersByTime(1500));
    expect(screen.getByRole("heading", { name: "Login destination" })).toBeVisible();
  });
});
