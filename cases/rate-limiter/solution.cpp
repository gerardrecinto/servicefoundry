// Reference implementation for the Rate Limiter design in README.md.
//
// Implements the token bucket LimitAlgorithm chosen in Tradeoffs.
#include <algorithm>  // std::min
#include <cstdio>     // printf
#include <mutex>      // std::mutex, std::lock_guard
#include <stdexcept>  // std::runtime_error
#include <string>
#include <unordered_map>

// Tier is a value object: (limit, window) pair a client is throttled against.
struct Tier {
    std::string name;      // human-readable label, e.g. "free" or "paid"
    double limit;          // max requests allowed per window
    double window_seconds; // length of that window, in seconds
};

// Maps a client id to its Tier, defaulting anyone unassigned.
class TierResolver {
public:
    explicit TierResolver(Tier default_tier) : default_(std::move(default_tier)) {} // fallback tier

    Tier resolve(const std::string& client_id) {
        std::lock_guard<std::mutex> lock(mu_);           // serialize against set_tier
        auto it = assignments_.find(client_id);
        if (it != assignments_.end()) return it->second; // explicit assignment wins
        return default_;                                 // else fall back to the default tier
    }

    void set_tier(const std::string& client_id, Tier tier) {
        std::lock_guard<std::mutex> lock(mu_);           // serialize against resolve
        assignments_[client_id] = std::move(tier);       // simulates a tier change landing
    }

private:
    std::mutex mu_;
    std::unordered_map<std::string, Tier> assignments_; // explicit per-client overrides
    Tier default_;
};

// One client's token bucket at a point in time.
struct BucketState {
    double tokens;      // tokens currently available to spend
    double last_refill; // timestamp tokens was last computed at
};

// Chosen over fixed-window in Tradeoffs: smooths bursts at a window
// boundary instead of allowing up to 2x the limit across two windows.
class TokenBucketAlgorithm {
public:
    // Returns {allowed, retry_after}.
    std::pair<bool, double> check(const std::string& client_id, const Tier& tier, double now) {
        double refill_rate = tier.limit / tier.window_seconds; // tokens regenerated per second
        std::lock_guard<std::mutex> lock(mu_);                 // serialize this client's bucket update
        auto it = buckets_.find(client_id);
        BucketState state = (it != buckets_.end()) ? it->second : BucketState{tier.limit, now}; // start full
        double tokens = std::min(tier.limit, state.tokens + (now - state.last_refill) * refill_rate); // refill
        if (tokens >= 1) {
            buckets_[client_id] = BucketState{tokens - 1, now}; // spend one token, reset baseline
            return {true, 0.0};                                 // allowed, no retry hint needed
        }
        buckets_[client_id] = BucketState{tokens, now}; // still record the refill baseline
        double missing = 1 - tokens;                    // fraction of a token still needed
        return {false, missing / refill_rate};          // denied, with a real retry_after
    }

private:
    std::mutex mu_;
    std::unordered_map<std::string, BucketState> buckets_; // per-client bucket state
};

// The check() operation from API Design: synchronous, in the request path
// of every protected API.
class RateLimiter {
public:
    explicit RateLimiter(TierResolver& tiers) : tiers_(tiers) {}

    std::pair<bool, double> check(const std::string& client_id, double now) {
        Tier tier = tiers_.resolve(client_id);       // look up this client's limit/window
        return algorithm_.check(client_id, tier, now); // delegate to the pluggable algorithm
    }

private:
    TierResolver& tiers_;
    TokenBucketAlgorithm algorithm_; // the chosen algorithm
};

int main() {
    Tier free{"free", 3, 1.0};   // 3 requests/second
    Tier paid{"paid", 10, 1.0};  // 10 requests/second
    TierResolver resolver(free); // everyone defaults to free
    resolver.set_tier("acme-paid", paid); // except this one client
    RateLimiter limiter(resolver);

    printf("-- free-tier client bursts past its limit --\n");
    double t0 = 0.0; // fixed instant in time, so the demo is deterministic
    for (int i = 0; i < 5; i++) {
        auto [allowed, retry_after] = limiter.check("acme-free", t0); // 5 requests against a limit of 3
        printf("request %d: allowed=%s retry_after=%.3fs\n", i, allowed ? "true" : "false", retry_after);
    }

    printf("\n-- paid-tier client has a higher ceiling at the same instant --\n");
    for (int i = 0; i < 5; i++) {
        auto [allowed, retry_after] = limiter.check("acme-paid", t0); // all 5 fit this tier's limit
        printf("request %d: allowed=%s retry_after=%.3fs\n", i, allowed ? "true" : "false", retry_after);
    }

    printf("\n-- free-tier client retries after the suggested retry_after --\n");
    auto [allowed, retry_after] = limiter.check("acme-free", t0); // still exhausted from the burst above
    if (allowed) throw std::runtime_error("expected denial"); // sanity check the demo setup is exhausted
    auto [allowed2, ignored] = limiter.check("acme-free", t0 + retry_after); // advance clock by retry_after
    printf("after waiting %.3fs: allowed=%s\n", retry_after, allowed2 ? "true" : "false"); // honored promise
    return 0;
}
