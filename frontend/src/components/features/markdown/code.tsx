import React from "react";
import { ExtraProps } from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { CopyableContentWrapper } from "#/components/shared/buttons/copyable-content-wrapper";

// See https://github.com/remarkjs/react-markdown?tab=readme-ov-file#use-custom-components-syntax-highlight

/**
 * Component to render code blocks in markdown.
 */
export function code({
  children,
  className,
}: React.ClassAttributes<HTMLElement> &
  React.HTMLAttributes<HTMLElement> &
  ExtraProps) {
  const match = /language-(\w+)/.exec(className || ""); // get the language
  const codeString = String(children).replace(/\n$/, "");

  // >>> CUSTOM: HiClaw — render ```thinking blocks as collapsible <details> <<<
  if (match && match[1] === "thinking") {
    // First non-empty line, trimmed and truncated, used as a hint of what
    // the model is thinking about so the user can decide whether to expand.
    const firstLine =
      codeString
        .split("\n")
        .map((l) => l.trim())
        .find((l) => l.length > 0) || "";
    const preview =
      firstLine.length > 80 ? `${firstLine.slice(0, 80)}…` : firstLine;
    return (
      <details
        className="my-2 rounded border border-neutral-700 bg-[#1b1e24] text-sm"
        data-testid="thinking-block"
      >
        <summary className="cursor-pointer select-none px-3 py-1.5 text-xs text-neutral-400 hover:text-neutral-200 flex items-center gap-2">
          {/* eslint-disable-next-line i18next/no-literal-string */}
          <span className="shrink-0">💭 Thinking</span>
          {preview && (
            <span className="truncate text-neutral-500 italic font-normal">
              {preview}
            </span>
          )}
        </summary>
        <div className="whitespace-pre-wrap px-3 pb-3 pt-1 text-xs leading-relaxed text-neutral-400">
          {codeString}
        </div>
      </details>
    );
  }
  // >>> END CUSTOM <<<

  if (!match) {
    const isMultiline = String(children).includes("\n");

    if (!isMultiline) {
      return (
        <code
          className={className}
          style={{
            backgroundColor: "#2a3038",
            padding: "0.2em 0.4em",
            borderRadius: "4px",
            color: "#e6edf3",
            border: "1px solid #30363d",
          }}
        >
          {children}
        </code>
      );
    }

    return (
      <CopyableContentWrapper text={codeString}>
        <pre
          style={{
            backgroundColor: "#2a3038",
            padding: "1em",
            borderRadius: "4px",
            color: "#e6edf3",
            border: "1px solid #30363d",
            overflow: "auto",
          }}
        >
          <code className={className}>{codeString}</code>
        </pre>
      </CopyableContentWrapper>
    );
  }

  return (
    <CopyableContentWrapper text={codeString}>
      <SyntaxHighlighter
        className="rounded-lg"
        style={vscDarkPlus}
        language={match?.[1]}
        PreTag="div"
      >
        {codeString}
      </SyntaxHighlighter>
    </CopyableContentWrapper>
  );
}
