import { beforeEach, describe, expect, it } from "vitest";
import { useVoiceStore } from "./voiceStore";

describe("voiceStore", () => {
  beforeEach(() => {
    useVoiceStore.setState({ recording: false, partialText: "" });
  });

  it("toggles recording", () => {
    useVoiceStore.getState().setRecording(true);
    expect(useVoiceStore.getState().recording).toBe(true);
    useVoiceStore.getState().setRecording(false);
    expect(useVoiceStore.getState().recording).toBe(false);
  });

  it("updates partial text", () => {
    useVoiceStore.getState().setPartialText("こんに");
    expect(useVoiceStore.getState().partialText).toBe("こんに");
    useVoiceStore.getState().setPartialText("こんにちは");
    expect(useVoiceStore.getState().partialText).toBe("こんにちは");
  });

  it("clearPartial resets the partial text", () => {
    useVoiceStore.getState().setPartialText("途中");
    useVoiceStore.getState().clearPartial();
    expect(useVoiceStore.getState().partialText).toBe("");
  });

  it("clearPartial leaves recording flag alone", () => {
    useVoiceStore.getState().setRecording(true);
    useVoiceStore.getState().setPartialText("x");
    useVoiceStore.getState().clearPartial();
    expect(useVoiceStore.getState().recording).toBe(true);
  });
});
