import { NextRequest, NextResponse } from 'next/server'
import { readFile, readdir } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import OpenAI from 'openai'

export const runtime = 'nodejs'
export const maxDuration = 60

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const companyName = (body.companyName ?? '').trim() || '御社'
    const productName = (body.productName ?? '').trim() || '当社のサービス'
    const issue = (body.issue ?? '').trim() || '業務効率化・コスト削減'

    const apiKey = process.env.OPENAI_API_KEY
    if (!apiKey) {
      return NextResponse.json(
        { error: 'APIキーが設定されていません。Vercel の Environment Variables で OPENAI_API_KEY を設定し、Redeploy してください。' },
        { status: 500 }
      )
    }

    let documentText = ''
    const docsDir = resolve(process.cwd(), 'docs')

    try {
      const names = await readdir(docsDir)
      for (const name of names) {
        if (!name.toLowerCase().endsWith('.txt')) continue
        const fullPath = join(docsDir, name)
        const content = await readFile(fullPath, 'utf-8')
        documentText += '\n\n--- ' + name + ' ---\n\n' + content
      }
      if (!documentText.trim()) {
        documentText = '（参考資料がありませんでした）'
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (msg.includes('ENOENT') || msg.includes('no such file')) {
        documentText = '（参考資料のフォルダが見つかりませんでした）'
      } else {
        documentText = '（参考資料の読み込みに失敗しました）'
      }
    }

    const maxChars = 10000
    const textForPrompt =
      documentText.length > maxChars
        ? documentText.slice(0, maxChars) + '\n\n... (以下省略)'
        : documentText

    const openai = new OpenAI({ apiKey })
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        {
          role: 'system',
          content:
            'あなたは営業提案文の作成を支援するアシスタントです。以下の参考資料の内容を踏まえて、具体的で説得力のある営業提案文を作成してください。敬語を使い、ビジネスメールの形式で出力してください。',
        },
        {
          role: 'user',
          content: `【参考資料】\n${textForPrompt}\n\n【依頼内容】\n会社名: ${companyName}\n商品/サービス名: ${productName}\n想定される課題: ${issue}\n\n上記参考資料を活用した営業提案文を作成してください。`,
        },
      ],
      temperature: 0.7,
      max_tokens: 2000,
    })

    const proposal =
      completion.choices[0]?.message?.content?.trim() || '提案文の生成に失敗しました。'

    return NextResponse.json({ proposal })
  } catch (error) {
    const message =
      error instanceof Error ? error.message : '不明なエラーが発生しました'
    return NextResponse.json(
      {
        error:
          message.includes('APIキー') || message.includes('OPENAI')
            ? message
            : '提案文の生成に失敗しました: ' + message,
      },
      { status: 500 }
    )
  }
}
