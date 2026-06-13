import './globals.css';
import type { Metadata } from 'next';
import { Nav } from '@/components/Nav';
import { UserWalletProvider } from '@/components/UserWallet';

export const metadata: Metadata = {
  title: 'Honeybee — long-tail research agents on Arc',
  description: 'Hire autonomous agents to research prediction markets. You stay in control of your funds.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <UserWalletProvider>
          <Nav />
          <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
        </UserWalletProvider>
      </body>
    </html>
  );
}
