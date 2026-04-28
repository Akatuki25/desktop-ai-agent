import type { AgentState, Emotion } from "../../store";

import smileImg from "./sprites/smile.png";
import neutralImg from "./sprites/neutral.png";
import thinkImg from "./sprites/think.png";
import surpriseImg from "./sprites/surprise.png";
import sadImg from "./sprites/sad.png";
import angryImg from "./sprites/angry.png";
import happyImg from "./sprites/happy.png";

const emotionToSprite: Record<Emotion, string> = {
  neutral: neutralImg,
  smile: smileImg,
  think: thinkImg,
  surprise: surpriseImg,
  sad: sadImg,
  angry: angryImg,
  happy: happyImg,
};

/**
 * Resolve the sprite image URL for the current state + emotion.
 *
 * - `hidden` state returns null (character is not rendered).
 * - `thinking` state forces the think sprite regardless of emotion.
 * - Default sprite (idle with no prior emotion) is the smile (キラキラ目).
 */
export function resolveSprite(
  state: AgentState,
  emotion: Emotion,
): string | null {
  if (state === "hidden") return null;
  if (state === "thinking") return thinkImg;
  return emotionToSprite[emotion] ?? smileImg;
}

/** The default "idle" sprite shown on first load. */
export const defaultSprite = smileImg;
