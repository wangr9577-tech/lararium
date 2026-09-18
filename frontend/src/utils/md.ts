import MarkdownIt from 'markdown-it'
import texmath from 'markdown-it-texmath'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const md = new MarkdownIt({
  html: false, // 只渲染自己写的 Markdown，不放大段 HTML
  linkify: true,
  breaks: false,
}).use(texmath, {
  engine: katex,
  delimiters: 'dollars',
  katexOptions: { throwOnError: false },
})

/** Markdown → HTML（含 KaTeX 公式） */
export function renderMd(src: string): string {
  try {
    return md.render(src || '')
  } catch {
    return md.render('*(渲染出错)*')
  }
}
