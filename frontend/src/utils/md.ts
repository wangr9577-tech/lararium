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

// html:false 会把 <br> 转义成纯文本，但 Vditor 编辑器在表格单元格内按 Enter 换行时，
// 会把单元格内容存成 <br />；若直接转义，阅读页会显示成字面的 "1<br />"，即换行丢失。
// 这里仅把「已被转义出来的 br」还原回真正的 <br> 标签（只此一个标签，不放行其它 HTML），
// 再交给 DOMPurify 兜底（<br> 在白名单内无害），html:false 的单点信任姿势保持不变。
const BR_ESCAPED = /&lt;br\s*\/?&gt;/gi

/** Markdown → HTML（含 KaTeX 公式，经 DOMPurify 净化） */
export function renderMd(src: string): string {
  try {
    return purify(md.render(src || '').replace(BR_ESCAPED, '<br>'))
  } catch {
    try {
      return purify(md.render('*(渲染出错)*'))
    } catch {
      return '<p>*(渲染出错)*</p>'
    }
  }
}
