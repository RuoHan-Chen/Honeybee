'use client';

import { Suspense, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

function TradesRedirectInner() {
  const router = useRouter();
  const sp = useSearchParams();

  useEffect(() => {
    const id = sp.get('id');
    router.replace('/inbox' + (id ? `?id=${encodeURIComponent(id)}` : ''));
  }, [router, sp]);

  return <p className="text-sm text-white/50">Redirecting to inbox…</p>;
}

/** Legacy route — redirects to /inbox preserving ?id= deep links. */
export default function TradesRedirect() {
  return (
    <Suspense fallback={null}>
      <TradesRedirectInner />
    </Suspense>
  );
}
