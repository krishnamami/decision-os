// Client-side export helpers. CSV/JSON are generated from data the page
// already has and downloaded via a Blob; PDF uses the browser's print-to-PDF
// (no PDF library is bundled).

export function dateStamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function triggerDownload(content: string, filename: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function csvCell(v: unknown): string {
  if (v == null) return ''
  const s = String(v)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

// `filenameBase` gets the date + extension appended, e.g. accord_pipeline_2026-06-09.csv
export function downloadCsv(headers: string[], rows: unknown[][], filenameBase: string): void {
  const lines = [headers.map(csvCell).join(','), ...rows.map((r) => r.map(csvCell).join(','))]
  // Leading BOM so Excel reads UTF-8 correctly.
  triggerDownload('﻿' + lines.join('\r\n'), `${filenameBase}_${dateStamp()}.csv`, 'text/csv;charset=utf-8')
}

export function downloadJson(obj: unknown, filenameBase: string): void {
  triggerDownload(JSON.stringify(obj, null, 2), `${filenameBase}_${dateStamp()}.json`, 'application/json')
}

export function printPdf(): void {
  // Dependency-free PDF: the browser's print dialog offers "Save as PDF".
  window.print()
}
