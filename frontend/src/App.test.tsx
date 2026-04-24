import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { useCharacterStore, useConnectionStore } from "./store";

describe("App", () => {
  beforeEach(() => {
    useCharacterStore.setState({ agentState: "idle", emotion: "neutral" });
    useConnectionStore.setState({ state: "idle" });
  });

  it("renders the character sprite", async () => {
    render(<App />);
    await waitFor(() => {
      const img = document.querySelector("img");
      expect(img).not.toBeNull();
    });
  });

  it("hides the input when not connected", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.queryByLabelText("message")).toBeNull();
    });
  });
});
