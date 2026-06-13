/**
 * Paper fill engine — pessimistic taker fills against the provided mid price.
 * Adds half-spread + slippage so we never overstate paper P&L.
 */
export interface OrderIn {
  venue: string;
  market_id: string;
  outcome: string;
  side: 'BUY' | 'SELL';
  limit_price: number;
  size_usd: number;
  max_slippage_bps: number;
  dry_run: boolean;
  idempotency_key: string;
}

export interface Fill {
  venue: string;
  market_id: string;
  outcome: string;
  side: 'BUY' | 'SELL';
  avg_price: number;
  filled_usd: number;
  fee_usd: number;
  paper: boolean;
}

const HALF_SPREAD = 0.005; // 50 bps each side, pessimistic for low-liquidity venues

export function paperFill(order: OrderIn, midPrice: number): Fill {
  const slip = (order.max_slippage_bps / 10_000);
  const px =
    order.side === 'BUY'
      ? Math.min(order.limit_price, midPrice + HALF_SPREAD + slip)
      : Math.max(order.limit_price, midPrice - HALF_SPREAD - slip);

  return {
    venue: order.venue,
    market_id: order.market_id,
    outcome: order.outcome,
    side: order.side,
    avg_price: Math.max(0.01, Math.min(0.99, Number(px.toFixed(4)))),
    filled_usd: order.size_usd,
    fee_usd: 0,
    paper: true,
  };
}
