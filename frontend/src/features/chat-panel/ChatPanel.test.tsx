import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";
import { useChatStore } from "../../store";

describe("ChatPanel", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
  });

  it("dispatches the text on Enter and clears the input", () => {
    const onSend = vi.fn();
    render(<ChatPanel onSend={onSend} />);
    const input = screen.getByLabelText("message") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("hello");
    expect(input.value).toBe("");
    expect(useChatStore.getState().messages).toHaveLength(1);
  });

  it("dispatches on send button click", () => {
    const onSend = vi.fn();
    render(<ChatPanel onSend={onSend} />);
    const input = screen.getByLabelText("message") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).toHaveBeenCalledWith("hi");
  });

  it("ignores whitespace-only input", () => {
    const onSend = vi.fn();
    render(<ChatPanel onSend={onSend} />);
    const input = screen.getByLabelText("message") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("disables the input and button when disabled prop is set", () => {
    render(<ChatPanel onSend={() => {}} disabled />);
    expect(screen.getByLabelText("message")).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });
});
