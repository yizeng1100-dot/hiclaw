/* eslint-disable i18next/no-literal-string */
import React from "react";

export function CommandSchedulerPage() {
  return (
    <div className="h-full flex flex-col text-white bg-[#0d1117]">
      <div className="px-5 py-3 border-b border-[#30363d]">
        <h1 className="text-base font-semibold">定时任务管理中心</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          配置和监控定时执行的 shell / python 脚本
        </p>
      </div>
      <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
        (placeholder — 任务列表将在下一步落地)
      </div>
    </div>
  );
}
