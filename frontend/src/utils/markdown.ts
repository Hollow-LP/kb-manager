import type MarkdownIt from 'markdown-it'
import MarkdownItCtor from 'markdown-it'
import hljs from 'highlight.js/lib/common'

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string)

const md: MarkdownIt = new MarkdownItCtor({
  html: false, // 模型输出不信任 HTML
  linkify: true,
  breaks: true,
  highlight(code: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch {
        /* 回退为纯文本 */
      }
    }
    return `<pre class="hljs"><code>${escapeHtml(code)}</code></pre>`
  },
})

export function renderMarkdown(text: string): string {
  return md.render(text || '')
}
