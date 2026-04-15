import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { Character } from "./Character";
import { useCharacterStore } from "../../store";

describe("Character", () => {
  beforeEach(() => {
    useCharacterStore.setState({ agentState: "idle", emotion: "neutral" });
  });

  it("renders a sprite placeholder for the current state/emotion", () => {
    render(<Character />);
    const el = screen.getByTestId("character");
    expect(el.getAttribute("data-state")).toBe("idle");
    expect(el.getAttribute("data-emotion")).toBe("neutral");
  });

  it("reacts to store updates", () => {
    render(<Character />);
    act(() => {
      useCharacterStore.setState({ agentState: "talking", emotion: "smile" });
    });
    const el = screen.getByTestId("character");
    expect(el.getAttribute("data-state")).toBe("talking");
    expect(el.getAttribute("data-emotion")).toBe("smile");
  });

  it("uses the thinking glyph when emotion is think", () => {
    useCharacterStore.setState({ agentState: "thinking", emotion: "think" });
    render(<Character />);
    expect(screen.getByTestId("character")).toHaveTextContent("…");
  });
});
