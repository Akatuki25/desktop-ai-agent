import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Bubble } from "./Bubble";
import type { ChatMessage } from "../../store";

function buildMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m0",
    role: "agent",
    text: "main",
    pending: false,
    ...overrides,
  };
}

describe("Bubble", () => {
  it("renders only the main layer when no thinking text is present", () => {
    render(<Bubble message={buildMessage({ text: "hello" })} />);
    expect(screen.getByTestId("bubble-text")).toHaveTextContent("hello");
    expect(screen.queryByTestId("bubble-thinking")).toBeNull();
  });

  it("renders both layers when the message has thinking content", () => {
    render(
      <Bubble
        message={buildMessage({ text: "answer", thinking: "planning" })}
      />,
    );
    expect(screen.getByTestId("bubble-thinking")).toHaveTextContent("planning");
    expect(screen.getByTestId("bubble-text")).toHaveTextContent("answer");
  });

  it("exposes role and pending state via data attributes", () => {
    render(
      <Bubble
        message={buildMessage({ role: "user", text: "hi", pending: false })}
      />,
    );
    const el = screen.getByTestId("bubble");
    expect(el.getAttribute("data-role")).toBe("user");
    expect(el.getAttribute("data-pending")).toBe("false");
  });
});
