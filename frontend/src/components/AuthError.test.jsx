import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AuthError, { formatAuthError } from "./AuthError";

describe("authentication errors", () => {
  it("shows a readable error and moves focus to it", () => {
    render(<AuthError message="Email is already registered" />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Email is already registered");
    expect(alert).toHaveFocus();
    expect(alert.scrollIntoView).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
  });
  it("does not render an empty alert", () => {
    render(<AuthError message="" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("brings a changed error into view", () => {
    const { rerender } = render(<AuthError message="First error" />);
    const scroll = vi.mocked(HTMLElement.prototype.scrollIntoView);
    scroll.mockClear();
    rerender(<AuthError message="Second error" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Second error");
    expect(scroll).toHaveBeenCalledOnce();
  });
  it("formats backend validation errors on separate lines", () => {
    expect(formatAuthError([
      { loc: ["body", "employee_id"], msg: "Invalid employee ID" },
      { loc: ["body", "password"], msg: "Too short" },
    ], "Failed")).toBe("employee id: Invalid employee ID\npassword: Too short");
  });
  it("handles plain errors and unknown response formats", () => {
    expect(formatAuthError("Email is already registered", "Failed")).toBe("Email is already registered");
    expect(formatAuthError(null, "Please try again")).toBe("Please try again");
  });
});
