'use client';
/**
 * UserWallet context.
 *
 * Today: localStorage-backed mock connect (address + manual/auto mode + per-agent limits).
 * Tomorrow: swap the connect() implementation for `usePrivy()` from
 * `@privy-io/react-auth` — the consumer API stays identical.
 */
import { createContext, useContext, useEffect, useState } from 'react';

export type ExecMode = 'manual' | 'auto';

export interface UserState {
  address: string | null;
  mode: ExecMode;
  perTradeLimit: number;
  dailyLimit: number;
  connect(address?: string): void;
  disconnect(): void;
  setMode(m: ExecMode): void;
  setPerTradeLimit(n: number): void;
  setDailyLimit(n: number): void;
}

const Ctx = createContext<UserState | null>(null);

const KEY = 'honeybee:user';

export function UserWalletProvider({ children }: { children: React.ReactNode }) {
  const [address, setAddress] = useState<string | null>(null);
  const [mode, setMode] = useState<ExecMode>('manual');
  const [perTradeLimit, setPerTradeLimit] = useState(25);
  const [dailyLimit, setDailyLimit] = useState(100);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const s = JSON.parse(raw);
        if (s.address) setAddress(s.address);
        if (s.mode) setMode(s.mode);
        if (typeof s.perTradeLimit === 'number') setPerTradeLimit(s.perTradeLimit);
        if (typeof s.dailyLimit === 'number') setDailyLimit(s.dailyLimit);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ address, mode, perTradeLimit, dailyLimit }));
    } catch { /* ignore */ }
  }, [address, mode, perTradeLimit, dailyLimit]);

  function connect(addr?: string) {
    if (addr) { setAddress(addr); return; }
    // Mock connect: synthesise an address. Replace with Privy login().
    const a = '0x' + Array.from(crypto.getRandomValues(new Uint8Array(20)))
      .map((b) => b.toString(16).padStart(2, '0')).join('');
    setAddress(a);
  }

  return (
    <Ctx.Provider value={{
      address, mode, perTradeLimit, dailyLimit,
      connect, disconnect: () => setAddress(null),
      setMode, setPerTradeLimit, setDailyLimit,
    }}>
      {children}
    </Ctx.Provider>
  );
}

export function useUser(): UserState {
  const c = useContext(Ctx);
  if (!c) throw new Error('useUser must be used inside UserWalletProvider');
  return c;
}
