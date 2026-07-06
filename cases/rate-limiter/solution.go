// Reference implementation for the Rate Limiter design in README.md.
//
// Implements the token bucket LimitAlgorithm chosen in Tradeoffs.
package main

import (
	"fmt"
	"sync"
)

type Tier struct {
	Name          string
	Limit         float64
	WindowSeconds float64
}

type TierResolver struct {
	mu          sync.Mutex
	assignments map[string]Tier
	def         Tier
}

func NewTierResolver(def Tier) *TierResolver {
	return &TierResolver{assignments: map[string]Tier{}, def: def}
}

func (r *TierResolver) Resolve(clientID string) Tier {
	r.mu.Lock()
	defer r.mu.Unlock()
	if t, ok := r.assignments[clientID]; ok {
		return t
	}
	return r.def
}

func (r *TierResolver) SetTier(clientID string, tier Tier) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.assignments[clientID] = tier
}

type bucketState struct {
	tokens     float64
	lastRefill float64
}

// TokenBucketAlgorithm smooths bursts at a window boundary instead of
// allowing up to 2x the limit across two fixed windows.
type TokenBucketAlgorithm struct {
	mu      sync.Mutex
	buckets map[string]bucketState
}

func NewTokenBucketAlgorithm() *TokenBucketAlgorithm {
	return &TokenBucketAlgorithm{buckets: map[string]bucketState{}}
}

func (a *TokenBucketAlgorithm) Check(clientID string, tier Tier, now float64) (bool, float64) {
	refillRate := tier.Limit / tier.WindowSeconds
	a.mu.Lock()
	defer a.mu.Unlock()
	state, ok := a.buckets[clientID]
	if !ok {
		state = bucketState{tokens: tier.Limit, lastRefill: now}
	}
	tokens := state.tokens + (now-state.lastRefill)*refillRate
	if tokens > tier.Limit {
		tokens = tier.Limit
	}
	if tokens >= 1 {
		a.buckets[clientID] = bucketState{tokens: tokens - 1, lastRefill: now}
		return true, 0
	}
	a.buckets[clientID] = bucketState{tokens: tokens, lastRefill: now}
	missing := 1 - tokens
	return false, missing / refillRate
}

type RateLimiter struct {
	tiers     *TierResolver
	algorithm *TokenBucketAlgorithm
}

func NewRateLimiter(tiers *TierResolver) *RateLimiter {
	return &RateLimiter{tiers: tiers, algorithm: NewTokenBucketAlgorithm()}
}

func (l *RateLimiter) Check(clientID string, now float64) (bool, float64) {
	tier := l.tiers.Resolve(clientID)
	return l.algorithm.Check(clientID, tier, now)
}

func main() {
	free := Tier{Name: "free", Limit: 3, WindowSeconds: 1.0}
	paid := Tier{Name: "paid", Limit: 10, WindowSeconds: 1.0}
	resolver := NewTierResolver(free)
	resolver.SetTier("acme-paid", paid)
	limiter := NewRateLimiter(resolver)

	fmt.Println("-- free-tier client bursts past its limit --")
	t0 := 0.0
	for i := 0; i < 5; i++ {
		allowed, retryAfter := limiter.Check("acme-free", t0)
		fmt.Printf("request %d: allowed=%v retry_after=%.3fs\n", i, allowed, retryAfter)
	}

	fmt.Println("\n-- paid-tier client has a higher ceiling at the same instant --")
	for i := 0; i < 5; i++ {
		allowed, retryAfter := limiter.Check("acme-paid", t0)
		fmt.Printf("request %d: allowed=%v retry_after=%.3fs\n", i, allowed, retryAfter)
	}

	fmt.Println("\n-- free-tier client retries after the suggested retry_after --")
	allowed, retryAfter := limiter.Check("acme-free", t0)
	if allowed {
		panic("expected denial")
	}
	allowed, _ = limiter.Check("acme-free", t0+retryAfter)
	fmt.Printf("after waiting %.3fs: allowed=%v\n", retryAfter, allowed)
}
