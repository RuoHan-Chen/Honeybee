import type { BrokerConnector, BrokerFill, RecommendationLite } from './types.js';
import { paperFill } from '../paper.js';

/** Default fallback connector — paper-fills using the recommendation's market price. */
function makePaperConnector(venue: 'polymarket' | 'kalshi' | 'gemini'): BrokerConnector {
  return {
    venue,
    async submitAsUser({ rec, maxSlippageBps }) {
      const fill = paperFill(
        {
          venue: rec.venue,
          market_id: rec.market_id,
          outcome: rec.outcome,
          side: rec.side,
          limit_price: rec.market_price + 0.01,
          size_usd: rec.suggested_size_usd,
          max_slippage_bps: maxSlippageBps,
          dry_run: true,
          idempotency_key: rec.rec_id,
        },
        rec.market_price,
      );
      return {
        rec_id: rec.rec_id,
        venue: rec.venue,
        market_id: rec.market_id,
        outcome: rec.outcome,
        side: rec.side,
        avg_price: fill.avg_price,
        filled_usd: fill.filled_usd,
        broker_ref: 'paper-' + rec.rec_id.slice(0, 8),
      } satisfies BrokerFill;
    },
  };
}

const REGISTRY: Record<string, BrokerConnector> = {
  polymarket: makePaperConnector('polymarket'),
  kalshi:     makePaperConnector('kalshi'),
  gemini:     makePaperConnector('gemini'),
};

export function getBroker(venue: string): BrokerConnector {
  const b = REGISTRY[venue];
  if (!b) throw new Error(`no broker connector for venue ${venue}`);
  return b;
}

export type { BrokerConnector, BrokerFill, RecommendationLite };
