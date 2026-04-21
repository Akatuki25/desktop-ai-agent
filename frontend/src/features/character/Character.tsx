import { useCharacterStore } from "../../store";
import { resolveSprite } from "./spriteMap";

export function Character() {
  const agentState = useCharacterStore((s) => s.agentState);
  const emotion = useCharacterStore((s) => s.emotion);
  const sprite = resolveSprite(agentState, emotion);

  if (sprite === null) {
    // hidden state — render nothing
    return <div data-testid="character" data-state="hidden" />;
  }

  return (
    <div
      data-testid="character"
      data-state={agentState}
      data-emotion={emotion}
      style={{
        textAlign: "center",
        transition: "opacity 150ms ease",
      }}
    >
      <img
        src={sprite}
        alt="agent character"
        style={{
          width: 160,
          height: "auto",
          imageRendering: "auto",
          pointerEvents: "none",
          userSelect: "none",
        }}
        draggable={false}
      />
    </div>
  );
}
