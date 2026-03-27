// >>> CUSTOM: HiClaw — Skill management via Gitea (through proxy) <<<
import React from "react";

export default function SkillManagement() {
  // Use proxy through app-server to avoid X-Frame-Options blocking
  const giteaUrl = "/runtime/gitea/hiclaw-admin/skills";
  const directUrl = `${window.location.protocol}//${window.location.hostname}:3300/hiclaw-admin/skills`;

  return (
    <div className="w-full h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 bg-[#25272D] border-b border-[#333] shrink-0">
        <span className="text-sm text-white font-medium">HiClaw Skills</span>
        <a
          href={directUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          Open in new tab ↗
        </a>
      </div>
      <iframe
        title="HiClaw Skills"
        src={giteaUrl}
        className="w-full border-0 flex-1"
      />
    </div>
  );
}
// >>> END CUSTOM <<<
