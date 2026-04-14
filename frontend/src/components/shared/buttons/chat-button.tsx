import { useNavigate, useLocation } from "react-router";
import { cn } from "#/utils/utils";

export function ChatButton() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const isActive = pathname.startsWith("/chat");

  return (
    <button
      type="button"
      onClick={() => navigate("/chat")}
      title="HiClaw Chat"
      aria-label="HiClaw Chat"
      className={cn(
        "w-[36px] h-[36px] rounded flex items-center justify-center transition",
        isActive
          ? "bg-blue-600 text-white"
          : "text-gray-400 hover:text-white hover:bg-[#333]",
      )}
    >
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    </button>
  );
}
