import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders header and shows closed status without daemon params", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /desktop-ai-agent/i })).toBeInTheDocument();
    expect(screen.getByTestId("status")).toHaveTextContent("status: closed");
  });

  it("exposes a labelled message input", () => {
    render(<App />);
    expect(screen.getByLabelText("message")).toBeInTheDocument();
  });
});
