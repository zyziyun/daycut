// post.md (written by vstudio.publish.post_body) -> title / description / tags for assisted fill.
// Layout: [title, ""], [hook, ""], body..., ["", "#tag #tag"]  (B站 uses a "标签：a, b" line instead).

export interface PostCopy {
  title: string;
  description: string;
  tags: string[];
}

const TAG_LINE = /^(#[^\s#]+\s*)+$/u;
const BILI_TAGS = /^标签[:：]\s*(.+)$/u;

export function parsePostCopy(md: string, manifestTitle = ''): PostCopy {
  const lines = md.replace(/\r\n/g, '\n').trim().split('\n');
  let title = manifestTitle.trim();
  if (lines.length && title && lines[0].trim() === title) {
    lines.shift();
  } else if (!title && lines.length > 1 && lines[1].trim() === '') {
    title = lines.shift()!.trim();
  }
  let tags: string[] = [];
  while (lines.length && lines[lines.length - 1].trim() === '') lines.pop();
  const last = lines.length ? lines[lines.length - 1].trim() : '';
  if (TAG_LINE.test(last)) {
    tags = last.split(/\s+/).map((t) => t.replace(/^#/, '')).filter(Boolean);
    lines.pop();
  } else {
    const m = BILI_TAGS.exec(last);
    if (m) {
      tags = m[1].split(/[,，、\s]+/).filter(Boolean);
      lines.pop();
    }
  }
  const description = lines.join('\n').trim();
  return { title, description, tags };
}

export function formatTags(tags: string[], format = '#{tag} ', max?: number): string {
  return tags
    .slice(0, max ?? tags.length)
    .map((t) => format.replace('{tag}', t))
    .join('')
    .trimEnd();
}
