/** @type {import('next').NextConfig} */
const nextConfig = {
  // pdf-parse はバンドルに含めるとエラーになるため、外部パッケージとして扱う
  experimental: {
    serverComponentsExternalPackages: ['pdf-parse'],
  },
}

module.exports = nextConfig
