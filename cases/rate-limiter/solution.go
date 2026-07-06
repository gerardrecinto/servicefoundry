// Reference implementation for the Rate Limiter design in README.md.
//
// Implements the token bucket LimitAlgorithm chosen in Tradeoffs.
package main

import (
	"fmt"  // demo output only
	"sync" // guards bucket/tier state against concurrent check() calls
)

// Tier is a value object: (limit, window) pair a client is billed/throttled against.
type Tier struct {
	Name          string  // human-readable label, e.g. "free" or "paid"
	Limit         float64 // max requests allowed per window
	WindowSeconds float64 // length of that window, in seconds
}

// TierResolver maps a client id to its Tier, defaulting anyone unassigned.
type TierResolver struct {
	mu          sync.Mutex      // protects assignments from concurrent reads/writes
	assignments map[string]Tier // explicit per-client overrides
	def         Tier            // fallback tier for everyone else
}

func NewTierResolver(def Tier) *TierResolver {
	return &TierResolver{assignments: map[string]Tier{}, def: def} // start with no explicit assignments
}

func (r *TierResolver) Resolve(clientID string) Tier {
	r.mu.Lock()         // serialize against SetTier
	defer r.mu.Unlock() // always release even if we return early
	if t, ok := r.assignments[clientID]; ok {
		return t // explicit assignment wins
	}
	return r.def // otherwise fall back to the default tier
}

func (r *TierResolver) SetTier(clientID string, tier Tier) {
	r.mu.Lock()                         // serialize against Resolve
	defer r.mu.Unlock()                 // release on return
	r.assignments[clientID] = tier      // simulates a tier change (e.g. an upgrade) landing
}

// bucketState is one client's token bucket at a point in time.
type bucketState struct {
	tokens     float64 // tokens currently available to spend
	lastRefill float64 // timestamp the tokens figure above was last computed at
}

// TokenBucketAlgorithm smooths bursts at a window boundary instead of
// allowing up to 2x the limit across two fixed windows.
type TokenBucketAlgorithm struct {
	mu      sync.Mutex             // protects buckets from concurrent Check calls
	buckets map[string]bucketState // per-client bucket state
}

func NewTokenBucketAlgorithm() *TokenBucketAlgorithm {
	return &TokenBucketAlgorithm{buckets: map[string]bucketState{}} // no clients tracked yet
}

func (a *TokenBucketAlgorithm) Check(clientID string, tier Tier, now float64) (bool, float64) {
	refillRate := tier.Limit / tier.WindowSeconds // tokens regenerated per second for this tier
	a.mu.Lock()                                   // serialize read-modify-write of this client's bucket
	defer a.mu.Unlock()                           // release once we've computed the result
	state, ok := a.buckets[clientID]
	if !ok {
		state = bucketState{tokens: tier.Limit, lastRefill: now} // start full the first time we see this client
	}
	tokens := state.tokens + (now-state.lastRefill)*refillRate // lazily refill based on elapsed time
	if tokens > tier.Limit {
		tokens = tier.Limit // never overflow the bucket's capacity
	}
	if tokens >= 1 {
		a.buckets[clientID] = bucketState{tokens: tokens - 1, lastRefill: now} // spend one token, reset baseline
		return true, 0                                                        // allowed, no retry hint needed
	}
	a.buckets[clientID] = bucketState{tokens: tokens, lastRefill: now} // still record the refill baseline
	missing := 1 - tokens                                              // fraction of a token still needed
	return false, missing / refillRate                                 // denied, with a real retry_after
}

// RateLimiter is the check() operation from API Design: synchronous, in
// the request path of every protected API.
type RateLimiter struct {
	tiers     *TierResolver
	algorithm *TokenBucketAlgorithm
}

func NewRateLimiter(tiers *TierResolver) *RateLimiter {
	return &RateLimiter{tiers: tiers, algorithm: NewTokenBucketAlgorithm()} // wire tiers + the chosen algorithm
}

func (l *RateLimiter) Check(clientID string, now float64) (bool, float64) {
	tier := l.tiers.Resolve(clientID)      // look up this client's limit/window
	return l.algorithm.Check(clientID, tier, now) // delegate to the pluggable algorithm
}

func main() {
	free := Tier{Name: "free", Limit: 3, WindowSeconds: 1.0}  // 3 requests/second
	paid := Tier{Name: "paid", Limit: 10, WindowSeconds: 1.0} // 10 requests/second
	resolver := NewTierResolver(free)                         // everyone defaults to free
	resolver.SetTier("acme-paid", paid)                       // except this one client
	limiter := NewRateLimiter(resolver)

	fmt.Println("-- free-tier client bursts past its limit --")
	t0 := 0.0 // fixed instant in time, so the demo is deterministic
	for i := 0; i < 5; i++ {
		allowed, retryAfter := limiter.Check("acme-free", t0) // 5 requests against a limit of 3
		fmt.Printf("request %d: allowed=%v retry_after=%.3fs\n", i, allowed, retryAfter)
	}

	fmt.Println("\n-- paid-tier client has a higher ceiling at the same instant --")
	for i := 0; i < 5; i++ {
		allowed, retryAfter := limiter.Check("acme-paid", t0) // same 5 requests, all fit under this tier's limit
		fmt.Printf("request %d: allowed=%v retry_after=%.3fs\n", i, allowed, retryAfter)
	}

	fmt.Println("\n-- free-tier client retries after the suggested retry_after --")
	allowed, retryAfter := limiter.Check("acme-free", t0) // still exhausted from the burst above
	if allowed {
		panic("expected denial") // sanity check that the demo setup is actually exhausted
	}
	allowed, _ = limiter.Check("acme-free", t0+retryAfter) // advance the clock by exactly retry_after
	fmt.Printf("after waiting %.3fs: allowed=%v\n", retryAfter, allowed) // proves retry_after is honored
}
