import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { Character } from "./Character";
import { useCharacterStore } from "../../store";

describe("Character", () => {
  beforeEach(() => {
    useCharacterStore.setState({ agentState: "idle", emotion: "neutral" });
  });

  it("renders an image for the current state/emotion", () => {
    render(<Character />);
    const el = screen.getByTestId("character");
    expect(el.getAttribute("data-state")).toBe("idle");
    expect(el.getAttribute("data-emotion")).toBe("neutral");
    expect(el.querySelector("img")).not.toBeNull();
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

  it("renders nothing visible when hidden", () => {
    useCharacterStore.setState({ agentState: "hidden", emotion: "neutral" });
    render(<Character />);
    const el = screen.getByTestId("character");
    expect(el.getAttribute("data-state")).toBe("hidden");
    expect(el.querySelector("img")).toBeNull();
  });
});
