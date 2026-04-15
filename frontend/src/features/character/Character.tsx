import { useCharacterStore } from "../../store";
import { resolveSprite } from "./spriteMap";

export function Character() {
  const agentState = useCharacterStore((s) => s.agentState);
  const emotion = useCharacterStore((s) => s.emotion);
  const sprite = resolveSprite(agentState, emotion);

  return (
    <div
      data-testid="character"
      data-state={agentState}
      data-emotion={emotion}
      className={sprite.cssClass}
      style={{
        fontFamily: "monospace",
        fontSize: 48,
        textAlign: "center",
        minHeight: 64,
      }}
    >
      {sprite.glyph}
    </div>
  );
}
