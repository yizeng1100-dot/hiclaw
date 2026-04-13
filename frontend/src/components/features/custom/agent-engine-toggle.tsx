// >>> CUSTOM: HiClaw <<<
import {
  useAgentEngineStore,
  type AgentEngine,
} from "#/stores/agent-engine-store";
import { useFilteredEvents } from "#/hooks/use-filtered-events";
import { cn } from "#/utils/utils";

type Option = { value: AgentEngine; label: string; desc: string };

const options: Option[] = [
  {
    value: "openhands_sdk",
    label: "OpenHands",
    desc: "Multi-model agent (default)",
  },
  { value: "claude_sdk", label: "Claude", desc: "Claude Agent SDK" },
];

/**
 * Agent engine toggle — only active/visible when creating a new conversation
 * (no user messages yet). Once a conversation has started, the engine is
 * frozen and this component hides itself to avoid confusing the user.
 *
 * Styled to match the conversation tab buttons (code/terminal/etc).
 */
export function AgentEngineToggle() {
  const { engine, setEngine } = useAgentEngineStore();
  const { userEventsExist } = useFilteredEvents();

  // Once the conversation has any messages, engine is locked-in; hide toggle
  if (userEventsExist) return null;

  return (
    <>
      {options.map((opt) => {
        const isActive = engine === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => setEngine(opt.value)}
            title={opt.desc}
            data-testid={`agent-engine-${opt.value}`}
            className={cn(
              "flex items-center gap-2 rounded-md cursor-pointer",
              "pl-1.5 pr-2 py-1 lg:py-1.5",
              "text-[#9299AA] bg-[#0D0F11]",
              isActive && "bg-[#25272D] text-white",
              isActive
                ? "hover:text-white hover:bg-tertiary"
                : "hover:text-white hover:bg-[#0D0F11]",
            )}
          >
            {/* small dot icon matching tab icon size */}
            <span
              className={cn(
                "w-2 h-2 rounded-full flex-shrink-0",
                isActive ? "bg-white" : "bg-[#9299AA]",
              )}
            />
            <span className="text-sm font-medium whitespace-nowrap">
              {opt.label}
            </span>
          </button>
        );
      })}
    </>
  );
}
// >>> END CUSTOM <<<
