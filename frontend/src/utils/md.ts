import MarkdownIt from 'markdown-it'
import texmath from 'markdown-it-texmath'
import katex from 'katex'
import DOMPurify from 'dompurify'
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

// P1-K1 纵深防御：markdown-it 的 html:false 是单点信任，任何解析器 0-day/
// 插件路径构造出的恶意标签再由 DOMPurify 兜底净化（默认配置保留 KaTeX 的
// span/svg/MathML 与内联 style，剥脚本与危险 URL）。
function purify(html: string): string {
  return DOMPurify.sanitize(html, { ADD_TAGS: ['use'], RETURN_TRUSTED_TYPE: false })
}

/** Markdown → HTML（含 KaTeX 公式，经 DOMPurify 净化） */
export function renderMd(src: string): string {
  try {
    return purify(md.render(src || ''))
  } catch {
    try {
      return purify(md.render('*(渲染出错)*'))
    } catch {
      return '<p>*(渲染出错)*</p>'
    }
  }
}
