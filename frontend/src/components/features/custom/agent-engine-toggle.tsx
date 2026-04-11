// >>> CUSTOM: HiClaw <<<
import { useAgentEngineStore, type AgentEngine } from "#/stores/agent-engine-store";

const options: { value: AgentEngine; label: string; desc: string }[] = [
  { value: "openhands_sdk", label: "OpenHands", desc: "Multi-model agent (default)" },
  { value: "claude_sdk", label: "Claude", desc: "Claude Agent SDK" },
];

export function AgentEngineToggle() {
  const { engine, setEngine } = useAgentEngineStore();

  return (
    <div className="flex items-center gap-1.5 rounded-lg bg-neutral-800 p-0.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => setEngine(opt.value)}
          className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs transition ${
            engine === opt.value
              ? "bg-neutral-600 text-white font-medium"
              : "text-neutral-400 hover:text-neutral-200"
          }`}
          title={opt.desc}
        >
          <span>{opt.label}</span>
        </button>
      ))}
    </div>
  );
}
// >>> END CUSTOM <<<
