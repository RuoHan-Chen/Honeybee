/**
 * Polymarket live execution stub.
 *
 * Implementation outline:
 *   - Use @polymarket/clob-client (or hand-rolled EIP-712 builder).
 *   - Sign order with the Privy-managed wallet (see ../wallet/privy.ts).
 *   - POST signed payload to https://clob.polymarket.com/order
 *   - Poll trades endpoint until filled / cancelled, return aggregated Fill.
 */
import type { Fill, OrderIn } from '../paper.js';

export async function submitPolymarket(_order: OrderIn): Promise<Fill> {
  throw new Error(
    'Polymarket live submission not implemented. Configure Privy + Polygon RPC, then wire @polymarket/clob-client here.'
  );
}
