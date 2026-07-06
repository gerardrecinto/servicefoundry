// Reference implementation for the Rate Limiter design in README.md.
//
// Implements the token bucket LimitAlgorithm chosen in Tradeoffs.
import java.util.HashMap;
import java.util.Map;

public class Solution {

    // Tier is a value object: (limit, window) pair a client is throttled against.
    static final class Tier {
        final String name;          // human-readable label, e.g. "free" or "paid"
        final double limit;         // max requests allowed per window
        final double windowSeconds; // length of that window, in seconds

        Tier(String name, double limit, double windowSeconds) {
            this.name = name;
            this.limit = limit;
            this.windowSeconds = windowSeconds;
        }
    }

    // Maps a client id to its Tier, defaulting anyone unassigned.
    static final class TierResolver {
        private final Map<String, Tier> assignments = new HashMap<>(); // explicit per-client overrides
        private final Tier defaultTier;                                // fallback for everyone else

        TierResolver(Tier defaultTier) {
            this.defaultTier = defaultTier;
        }

        synchronized Tier resolve(String clientId) {
            return assignments.getOrDefault(clientId, defaultTier); // explicit assignment wins, else default
        }

        synchronized void setTier(String clientId, Tier tier) {
            assignments.put(clientId, tier); // simulates a tier change (e.g. an upgrade) landing
        }
    }

    // One client's token bucket at a point in time.
    static final class BucketState {
        double tokens;     // tokens currently available to spend
        double lastRefill; // timestamp tokens was last computed at

        BucketState(double tokens, double lastRefill) {
            this.tokens = tokens;
            this.lastRefill = lastRefill;
        }
    }

    // Chosen over fixed-window in Tradeoffs: smooths bursts at a window
    // boundary instead of allowing up to 2x the limit across two windows.
    static final class TokenBucketAlgorithm {
        private final Map<String, BucketState> buckets = new HashMap<>(); // per-client bucket state

        synchronized double[] check(String clientId, Tier tier, double now) {
            double refillRate = tier.limit / tier.windowSeconds; // tokens regenerated per second for this tier
            BucketState state = buckets.get(clientId);
            if (state == null) {
                state = new BucketState(tier.limit, now); // start full the first time we see this client
            }
            double tokens = state.tokens + (now - state.lastRefill) * refillRate; // lazily refill
            tokens = Math.min(tokens, tier.limit);                                // never overflow capacity
            if (tokens >= 1) {
                buckets.put(clientId, new BucketState(tokens - 1, now)); // spend one token, reset baseline
                return new double[]{1.0, 0.0};                          // 1.0 = allowed, no retry hint needed
            }
            buckets.put(clientId, new BucketState(tokens, now)); // still record the refill baseline
            double missing = 1 - tokens;                          // fraction of a token still needed
            return new double[]{0.0, missing / refillRate};       // 0.0 = denied, with a real retry_after
        }
    }

    // The check() operation from API Design: synchronous, in the request
    // path of every protected API.
    static final class RateLimiter {
        private final TierResolver tiers;
        private final TokenBucketAlgorithm algorithm = new TokenBucketAlgorithm(); // the chosen algorithm

        RateLimiter(TierResolver tiers) {
            this.tiers = tiers;
        }

        double[] check(String clientId, double now) {
            Tier tier = tiers.resolve(clientId);          // look up this client's limit/window
            return algorithm.check(clientId, tier, now);  // delegate to the pluggable algorithm
        }
    }

    public static void main(String[] args) {
        Tier free = new Tier("free", 3, 1.0);   // 3 requests/second
        Tier paid = new Tier("paid", 10, 1.0);  // 10 requests/second
        TierResolver resolver = new TierResolver(free); // everyone defaults to free
        resolver.setTier("acme-paid", paid);            // except this one client
        RateLimiter limiter = new RateLimiter(resolver);

        System.out.println("-- free-tier client bursts past its limit --");
        double t0 = 0.0; // fixed instant in time, so the demo is deterministic
        for (int i = 0; i < 5; i++) {
            double[] result = limiter.check("acme-free", t0); // 5 requests against a limit of 3
            System.out.printf("request %d: allowed=%s retry_after=%.3fs%n", i, result[0] == 1.0, result[1]);
        }

        System.out.println("\n-- paid-tier client has a higher ceiling at the same instant --");
        for (int i = 0; i < 5; i++) {
            double[] result = limiter.check("acme-paid", t0); // same 5 requests, all fit this tier's limit
            System.out.printf("request %d: allowed=%s retry_after=%.3fs%n", i, result[0] == 1.0, result[1]);
        }

        System.out.println("\n-- free-tier client retries after the suggested retry_after --");
        double[] denied = limiter.check("acme-free", t0); // still exhausted from the burst above
        if (denied[0] == 1.0) {
            throw new IllegalStateException("expected denial"); // sanity check the demo setup is exhausted
        }
        double retryAfter = denied[1];
        double[] retried = limiter.check("acme-free", t0 + retryAfter); // advance the clock by retry_after
        System.out.printf("after waiting %.3fs: allowed=%s%n", retryAfter, retried[0] == 1.0); // honored promise
    }
}
