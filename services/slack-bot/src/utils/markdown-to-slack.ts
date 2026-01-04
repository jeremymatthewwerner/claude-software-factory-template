/**
 * Convert markdown to Slack mrkdwn format
 */

export function markdownToSlack(markdown: string): string {
  let text = markdown;

  // Convert headers (Slack doesn't support headers, make them bold)
  text = text.replace(/^### (.+)$/gm, '*$1*');
  text = text.replace(/^## (.+)$/gm, '*$1*');
  text = text.replace(/^# (.+)$/gm, '*$1*');

  // Convert bold: **text** or __text__ -> *text*
  text = text.replace(/\*\*(.+?)\*\*/g, '*$1*');
  text = text.replace(/__(.+?)__/g, '*$1*');

  // Convert italic: *text* or _text_ -> _text_
  // Note: We need to be careful not to convert already-bold text
  text = text.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '_$1_');

  // Convert strikethrough: ~~text~~ -> ~text~
  text = text.replace(/~~(.+?)~~/g, '~$1~');

  // Convert inline code: `code` stays the same
  // Already works in Slack

  // Convert code blocks: ```lang\ncode\n``` -> ```code```
  text = text.replace(/```(\w*)\n([\s\S]*?)```/g, '```$2```');

  // Convert links: [text](url) -> <url|text>
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<$2|$1>');

  // Convert blockquotes: > text -> > text (stays the same, Slack supports it)

  // Convert horizontal rules
  text = text.replace(/^[-*_]{3,}$/gm, '───────────────────');

  // Convert unordered lists: - item or * item stays mostly the same
  // Slack prefers • but - works too

  // Convert ordered lists: 1. item stays the same

  // Truncate if too long for Slack (max 40000 chars per message)
  if (text.length > 39000) {
    text = text.substring(0, 39000) + '\n\n_...message truncated..._';
  }

  return text;
}

/**
 * Split long messages into chunks for Slack
 */
export function splitMessage(text: string, maxLength: number = 3900): string[] {
  if (text.length <= maxLength) {
    return [text];
  }

  const chunks: string[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    if (remaining.length <= maxLength) {
      chunks.push(remaining);
      break;
    }

    // Try to split at a natural boundary
    let splitIndex = maxLength;

    // Look for newline
    const newlineIndex = remaining.lastIndexOf('\n', maxLength);
    if (newlineIndex > maxLength * 0.5) {
      splitIndex = newlineIndex + 1;
    } else {
      // Look for space
      const spaceIndex = remaining.lastIndexOf(' ', maxLength);
      if (spaceIndex > maxLength * 0.5) {
        splitIndex = spaceIndex + 1;
      }
    }

    chunks.push(remaining.substring(0, splitIndex));
    remaining = remaining.substring(splitIndex);
  }

  return chunks;
}

/**
 * Format code block for Slack
 */
export function formatCodeBlock(code: string, language?: string): string {
  // Slack doesn't support language hints, just use triple backticks
  return '```\n' + code + '\n```';
}

/**
 * Escape special characters for Slack
 */
export function escapeSlack(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
