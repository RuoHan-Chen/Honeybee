import './globals.css';
import type { Metadata } from 'next';
import { ChatShell } from '@/components/ChatShell';
import { UserWalletProvider } from '@/components/UserWallet';
import { AutoPilot } from '@/components/AutoPilot';
import { display, mono, sans } from '@/lib/fonts';

export const metadata: Metadata = {
  title: 'Honeybee — research agents for prediction markets',
  description: 'Hire agents to research niche markets. You keep custody and approve every trade.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body className="font-sans antialiased">
        <UserWalletProvider>
          <AutoPilot />
          <ChatShell>{children}</ChatShell>
        </UserWalletProvider>
      </body>
    </html>
  );
}
