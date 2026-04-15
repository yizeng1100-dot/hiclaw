import { useNavigate, useLocation } from "react-router";
import { cn } from "#/utils/utils";

export function CommandSchedulerButton() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const isActive = pathname.startsWith("/command-scheduler");
  return (
    <button
      type="button"
      onClick={() => navigate("/command-scheduler")}
      title="定时任务中心"
      aria-label="定时任务中心"
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
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <circle cx="12" cy="15" r="2" />
      </svg>
    </button>
  );
}
