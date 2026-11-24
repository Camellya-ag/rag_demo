export function highlightTerms(text, query) {
  const terms = [...new Set(
    (String(query || '').match(/[一-龥]{2,4}/g) || []).concat(
      (String(query || '').match(/[a-zA-Z0-9]{2,}/g) || [])
    )
  )]
    .filter((w) => w.length >= 2)
    .sort((a, b) => b.length - a.length)
    .slice(0, 8)

  if (!terms.length) return text
  const escaped = terms.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`(${escaped.join('|')})`, 'g')
  return String(text || '').replace(re, '<mark>$1</mark>')
}
