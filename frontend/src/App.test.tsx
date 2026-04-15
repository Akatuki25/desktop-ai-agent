import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { useChatStore, useCharacterStore, useConnectionStore } from "./store";

describe("App", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
    useCharacterStore.setState({ agentState: "idle", emotion: "neutral" });
    useConnectionStore.setState({ state: "idle" });
  });

  it("renders the character and chat panel shells", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /desktop-ai-agent/i })).toBeInTheDocument();
    expect(screen.getByTestId("character")).toBeInTheDocument();
    expect(screen.getByTestId("chat-panel")).toBeInTheDocument();
  });

  it("settles to closed status when no port/token query is present", async () => {
    render(<App />);
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("status: closed"),
    );
  });

  it("disables the message input until the connection opens", async () => {
    render(<App />);
    await waitFor(() => {
      const input = screen.getByLabelText("message") as HTMLInputElement;
      expect(input).toBeDisabled();
    });
  });
});
