/**
 * Kalshi live execution stub.
 *
 * Implementation outline:
 *   - POST /trade-api/v2/login with KALSHI_EMAIL+PASSWORD → bearer token.
 *   - POST /portfolio/orders with bearer token + order payload.
 *   - Poll /portfolio/fills until filled, aggregate, return Fill.
 */
import type { Fill, OrderIn } from '../paper.js';

export async function submitKalshi(_order: OrderIn): Promise<Fill> {
  throw new Error(
    'Kalshi live submission not implemented. Set KALSHI_EMAIL + KALSHI_PASSWORD and wire HTTP calls here.'
  );
}
