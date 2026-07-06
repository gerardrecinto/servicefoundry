# Reference implementation for the Rate Limiter design in README.md.
#
# Implements the token bucket LimitAlgorithm chosen in Tradeoffs.
require "thread" # Mutex, used to guard bucket/tier state against concurrent check() calls

# Tier is a value object: (limit, window) pair a client is throttled against.
Tier = Struct.new(:name, :limit, :window_seconds) # name label; limit per window; window length in seconds

# Maps a client id to its Tier, defaulting anyone unassigned.
class TierResolver
  def initialize(default_tier)
    @assignments = {}          # explicit per-client overrides
    @default = default_tier    # fallback tier for everyone else
    @mutex = Mutex.new         # protects @assignments
  end

  def resolve(client_id)
    @mutex.synchronize { @assignments.fetch(client_id, @default) } # explicit wins, else default
  end

  def set_tier(client_id, tier)
    @mutex.synchronize { @assignments[client_id] = tier } # simulates a tier change landing
  end
end

# Chosen over fixed-window in Tradeoffs: smooths bursts at a window
# boundary instead of allowing up to 2x the limit across two windows.
class TokenBucketAlgorithm
  BucketState = Struct.new(:tokens, :last_refill) # tokens available; timestamp last computed at

  def initialize
    @buckets = {}       # client_id -> BucketState
    @mutex = Mutex.new  # protects @buckets
  end

  # Returns [allowed, retry_after].
  def check(client_id, tier, now)
    refill_rate = tier.limit.to_f / tier.window_seconds # tokens regenerated per second for this tier
    @mutex.synchronize do
      state = @buckets[client_id] || BucketState.new(tier.limit.to_f, now) # start full on first sight
      tokens = [tier.limit.to_f, state.tokens + (now - state.last_refill) * refill_rate].min # lazy refill
      if tokens >= 1
        @buckets[client_id] = BucketState.new(tokens - 1, now) # spend one token, reset baseline
        return [true, 0.0]                                     # allowed, no retry hint needed
      end
      @buckets[client_id] = BucketState.new(tokens, now) # still record the refill baseline
      missing = 1 - tokens                                # fraction of a token still needed
      [false, missing / refill_rate]                      # denied, with a real retry_after
    end
  end
end

# The check() operation from API Design: synchronous, in the request path
# of every protected API.
class RateLimiter
  def initialize(tier_resolver, algorithm = TokenBucketAlgorithm.new)
    @tiers = tier_resolver   # resolves client_id -> Tier
    @algorithm = algorithm   # the chosen algorithm
  end

  def check(client_id, now:)
    tier = @tiers.resolve(client_id)          # look up this client's limit/window
    @algorithm.check(client_id, tier, now)    # delegate to the pluggable algorithm
  end
end

if __FILE__ == $PROGRAM_NAME
  free = Tier.new("free", 3, 1.0)                          # 3 requests/second
  paid = Tier.new("paid", 10, 1.0)                         # 10 requests/second
  resolver = TierResolver.new(free)                        # everyone defaults to free
  resolver.set_tier("acme-paid", paid)                     # except this one client
  limiter = RateLimiter.new(resolver)

  puts "-- free-tier client bursts past its limit --"
  t0 = 0.0 # fixed instant in time, so the demo is deterministic
  5.times do |i|
    allowed, retry_after = limiter.check("acme-free", now: t0) # 5 requests against a limit of 3
    puts "request #{i}: allowed=#{allowed} retry_after=#{'%.3f' % retry_after}s"
  end

  puts "\n-- paid-tier client has a higher ceiling at the same instant --"
  5.times do |i|
    allowed, retry_after = limiter.check("acme-paid", now: t0) # all 5 fit this tier's limit
    puts "request #{i}: allowed=#{allowed} retry_after=#{'%.3f' % retry_after}s"
  end

  puts "\n-- free-tier client retries after the suggested retry_after --"
  allowed, retry_after = limiter.check("acme-free", now: t0) # still exhausted from the burst above
  raise "expected denial" if allowed                          # sanity check the demo setup is exhausted
  allowed, = limiter.check("acme-free", now: t0 + retry_after) # advance the clock by exactly retry_after
  puts "after waiting #{'%.3f' % retry_after}s: allowed=#{allowed}" # proves retry_after is honored
end
