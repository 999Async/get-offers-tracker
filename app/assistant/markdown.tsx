import { Fragment } from "react";

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => part.startsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> : part.startsWith("`") ? <code key={index}>{part.slice(1, -1)}</code> : <Fragment key={index}>{part}</Fragment>);
}

// Deliberately render text, not HTML. Links/actions come from validated source cards.
export default function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    if (line.startsWith("```")) {
      const code = []; const key = i;
      while (++i < lines.length && !lines[i].startsWith("```")) code.push(lines[i]);
      blocks.push(<pre key={key}><code>{code.join("\n")}</code></pre>);
    } else if (/^#{1,4} /.test(line)) {
      blocks.push(<h3 key={i}>{inline(line.replace(/^#{1,4} /, ""))}</h3>);
    } else if (/^\s*[-*] /.test(line) || /^\s*\d+[.)] /.test(line)) {
      const ordered = /^\s*\d+[.)] /.test(line), items = [], key = i;
      const pattern = ordered ? /^\s*\d+[.)] / : /^\s*[-*] /;
      while (i < lines.length && pattern.test(lines[i])) { items.push(<li key={i}>{inline(lines[i].replace(pattern, ""))}</li>); i++; }
      i--; blocks.push(ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
    } else blocks.push(<p key={i}>{inline(line)}</p>);
  }
  return <div className="assistant-markdown">{blocks}</div>;
}
