import type { AgentState, Emotion } from "../../store";

/**
 * Static placeholder. When real PNG sprite sheets land, this becomes
 * `state×emotion → image URL`; for now we just return a symbolic
 * descriptor so the Character component can show something verifiable.
 */
export interface SpriteDescriptor {
  glyph: string;
  cssClass: string;
}

export function resolveSprite(state: AgentState, emotion: Emotion): SpriteDescriptor {
  if (state === "hidden") return { glyph: " ", cssClass: `sprite hidden` };
  if (state === "thinking" || emotion === "think") {
    return { glyph: "…", cssClass: "sprite think" };
  }
  const glyph = (
    {
      neutral: "・_・",
      smile: "^_^",
      surprise: "o_o",
      sad: "T_T",
      angry: ">_<",
      think: "…",
    } satisfies Record<Emotion, string>
  )[emotion];
  return { glyph, cssClass: `sprite ${emotion} state-${state}` };
}
