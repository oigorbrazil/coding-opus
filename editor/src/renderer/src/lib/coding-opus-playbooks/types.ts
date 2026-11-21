// Types the Coding Agent 1 playbooks editor reads, copied from its src/lib/types.ts.

export type AgentType = string
export type Theme = string

export type OrchestrationRole = {
  name: string
  agent: 'codex' | 'claude'
  /** null runs the CLI's default model. */
  model: string | null
  /** Reasoning effort, as the chosen CLI names it; null keeps the CLI's setting. */
  effort: string | null
  /** Codex read-only sandbox. Always false for Claude. */
  readOnly: boolean
  /** null uses the default budget; 0 lets the worker run without a limit. */
  timeoutSeconds: number | null
  /**
   * Another role to run instead while this one's provider is past 80% of its quota. A read-only
   * role only falls back to a read-only one.
   */
  fallback?: string | null
  /**
   * The planner agent this row is for; absent serves any planner. A row for the planner's own agent
   * wins over the row for any with the same name.
   */
  orchestrator?: 'claude' | 'codex'
}

/** Task category the planner reports on a delegate call; drives routing rules. */
export type DelegateKind = 'research' | 'code' | 'review' | 'command' | 'scrap' | 'docs'

/** Coarse effort the planner assigns to a delegated task; drives routing rules. */
export type EffortClass = 'light' | 'standard' | 'deep'

/** A quota condition: the named window must sit below `below` percent for the rule to fire. */
export type QuotaGate = {
  agent: 'claude' | 'codex'
  /** Claude: 5h / 7d / 7d-Opus. Codex reads 'opus' as its secondary (weekly) window. */
  window: 'short' | 'week' | 'opus'
  below: number
}

/** First matching enabled rule wins; the delegate call runs as the named role. */
export type RoutingRule = {
  id: string
  enabled: boolean
  /** Kinds the rule matches; empty matches any kind. */
  kinds: DelegateKind[]
  /** Effort classes the rule matches; empty matches any effort. */
  efforts: EffortClass[]
  /** Every gate must pass for the rule to fire. */
  gates: QuotaGate[]
  /** Name of the OrchestrationRole the matching call runs as. */
  role: string
}

export type ClaudeUsageWindow = {
  utilization: number
  resets_at: string
}

/** A weekly limit scoped to one model other than Opus, such as Fable. */
export type ClaudeModelLimit = {
  model: string
  utilization: number
  resets_at: string
}

export type ClaudeUsage = {
  five_hour: ClaudeUsageWindow
  seven_day: ClaudeUsageWindow
  seven_day_opus: ClaudeUsageWindow
  model_limits?: ClaudeModelLimit[]
}

export type CodexUsageWindow = {
  used_percent: number
  window_minutes: number
  /** Epoch in milliseconds (0 = unknown). */
  resets_at_ms: number
}

export type CodexUsage = {
  primary: CodexUsageWindow
  secondary: CodexUsageWindow
  plan: string
  rate_limited: boolean
  reset_credits: number
}
