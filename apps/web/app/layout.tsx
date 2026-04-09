import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "競艇予想アプリ",
  description: "期待値1.2以上の舟券をアラート表示する競艇予想ダッシュボード",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        <header className="border-b bg-white px-6 py-4">
          <nav className="mx-auto flex max-w-7xl items-center justify-between">
            <h1 className="text-xl font-bold">競艇予想</h1>
            <div className="flex gap-4 text-sm">
              <a href="/dashboard" className="hover:text-blue-600">ダッシュボード</a>
              <a href="/bets" className="hover:text-blue-600">購入記録</a>
              <a href="/analytics" className="hover:text-blue-600">収支分析</a>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
