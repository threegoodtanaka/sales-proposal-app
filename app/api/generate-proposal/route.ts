import { NextRequest, NextResponse } from 'next/server'
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import { PDFParse } from 'pdf-parse'
import OpenAI from 'openai'

export async function POST(request: NextRequest) {
  try {
    const { companyName, productName, issue } = await request.json()
    const c = (companyName || '').trim() || '御社'
    const p = (productName || '').trim() || '当社のサービス'
    const i = (issue || '').trim() || '業務効率化・コスト削減'

    const apiKey = process.env.OPENAI_API_KEY
    if (!apiKey) {
      return NextResponse.json(
        { error: 'OPENAI_API_KEY が設定されていません。.env ファイルを確認してください。' },
        { status: 500 }
      )
    }

    // docs フォルダ内の PDF を読み込み
    const docsDir = path.join(process.cwd(), 'docs')
    let documentText = ''

    try {
      const files = await readdir(docsDir)
      const pdfFiles = files.filter((f) => f.toLowerCase().endsWith('.pdf'))

      for (const pdfFile of pdfFiles) {
        const pdfPath = path.join(docsDir, pdfFile)
        const buffer = await readFile(pdfPath)
        const parser = new PDFParse({ data: buffer })
        try {
          const result = await parser.getText()
          documentText += `\n\n--- ${pdfFile} ---\n\n${result.text}`
        } finally {
          await parser.destroy()
        }
      }

      if (!documentText.trim()) {
        documentText = '（参考資料がありませんでした）'
      }
    } catch (err) {
      console.error('PDF読み込みエラー:', err)
      documentText = '（参考資料の読み込みに失敗しました）'
    }

    // トークン制限のため、長すぎる場合は先頭部分を使用（目安: 約10000文字）
    const maxChars = 10000
    const truncatedText =
      documentText.length > maxChars
        ? documentText.slice(0, maxChars) + '\n\n... (以下省略)'
        : documentText

    const openai = new OpenAI({ apiKey })
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        {
          role: 'system',
          content: `あなたは営業提案文の作成を支援するアシスタントです。
以下の参考資料（ホワイトペーパー・事例集など）の内容を踏まえて、具体的で説得力のある営業提案文を作成してください。
参考資料に含まれる事例・データ・特徴・強みを可能な限り反映し、テンプレート的な表現を避けてください。
敬語を使い、ビジネスメールの形式で出力してください。`,
        },
        {
          role: 'user',
          content: `【参考資料】
${truncatedText}

【依頼内容】
以下の情報を基に、上記参考資料を活用した営業提案文を作成してください。

・会社名: ${c}
・商品/サービス名: ${p}
・想定される課題: ${i}`,
        },
      ],
      temperature: 0.7,
      max_tokens: 2000,
    })

    const proposalText =
      completion.choices[0]?.message?.content?.trim() ||
      '提案文の生成に失敗しました。'

    return NextResponse.json({ proposal: proposalText })
  } catch (error) {
    console.error('APIエラー:', error)
    const message =
      error instanceof Error ? error.message : '不明なエラーが発生しました'
    return NextResponse.json(
      { error: `提案文の生成に失敗しました: ${message}` },
      { status: 500 }
    )
  }
}
