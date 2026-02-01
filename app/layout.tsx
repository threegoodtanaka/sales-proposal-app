import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: '営業提案文作成アプリ',
  description: '会社名・商品名・課題から営業提案文を生成',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  )
}
