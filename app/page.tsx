'use client'

import { useState } from 'react'

export default function SalesProposalPage() {
  const [companyName, setCompanyName] = useState('')
  const [productName, setProductName] = useState('')
  const [issue, setIssue] = useState('')
  const [generatedText, setGeneratedText] = useState('')
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleGenerate = async () => {
    setLoading(true)
    setError('')
    setGeneratedText('')
    setCopied(false)

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 90000)

    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          companyName,
          productName,
          issue,
        }),
        signal: controller.signal,
      })

      clearTimeout(timeoutId)

      const contentType = res.headers.get('content-type') ?? ''
      const text = await res.text()

      if (!contentType.includes('application/json')) {
        const msg = text.startsWith('<!')
          ? 'サーバーでエラーが発生しました。しばらくしてから再試行するか、Vercel のログを確認してください。'
          : text.slice(0, 300)
        throw new Error(msg)
      }

      const data = JSON.parse(text)

      if (!res.ok) {
        throw new Error(data.error || '提案文の生成に失敗しました')
      }

      setGeneratedText(data.proposal || '')
    } catch (err) {
      if (err instanceof Error) {
        if (err.name === 'AbortError') {
          setError('タイムアウトしました。時間をおいて再度お試しください。')
        } else if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
          setError('ネットワークエラーです。接続を確認して再度お試しください。')
        } else {
          setError(err.message)
        }
      } else {
        setError('予期しないエラーが発生しました')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async () => {
    if (!generatedText) return
    try {
      await navigator.clipboard.writeText(generatedText)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      alert('コピーに失敗しました')
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 py-10 px-4 sm:px-6 lg:px-8">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold text-slate-800 mb-8 text-center">
          営業提案文作成
        </h1>

        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-5">
          <div>
            <label htmlFor="company" className="block text-sm font-medium text-slate-700 mb-1">
              会社名
            </label>
            <input
              id="company"
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="例：株式会社〇〇"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
            />
          </div>

          <div>
            <label htmlFor="product" className="block text-sm font-medium text-slate-700 mb-1">
              商品名
            </label>
            <input
              id="product"
              type="text"
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="例：業務効率化ツールA"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
            />
          </div>

          <div>
            <label htmlFor="issue" className="block text-sm font-medium text-slate-700 mb-1">
              課題
            </label>
            <textarea
              id="issue"
              value={issue}
              onChange={(e) => setIssue(e.target.value)}
              placeholder="例：業務の属人化により、属人リスクや稼働の偏りが発生している"
              rows={3}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition resize-none"
            />
          </div>

          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading}
            className="w-full py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {loading ? '生成中...' : '提案文を生成'}
          </button>

          {error && (
            <div className="p-3 text-sm text-red-600 bg-red-50 rounded-lg border border-red-200">
              {error}
            </div>
          )}
        </div>

        {generatedText && (
          <div className="mt-8 bg-white rounded-xl shadow-sm border border-slate-200 p-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold text-slate-800">生成された提案文</h2>
              <button
                type="button"
                onClick={handleCopy}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 focus:ring-2 focus:ring-slate-400 transition"
              >
                {copied ? 'コピーしました！' : 'コピー'}
              </button>
            </div>
            <pre className="whitespace-pre-wrap text-slate-700 text-sm leading-relaxed p-4 bg-slate-50 rounded-lg border border-slate-200 overflow-x-auto">
              {generatedText}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
