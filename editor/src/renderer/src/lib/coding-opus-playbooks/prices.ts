import table from '../../../../../../skills/coding/prices.json'

export type ModelPrice = { input: number; output: number }

const PRICES: Record<string, ModelPrice> = Object.fromEntries(
  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: prices.json ships with the skill in this shape.
  Object.entries(table.models as Record<string, { input?: unknown; output?: unknown }>)
    .filter(([, entry]) => typeof entry.input === 'number' && typeof entry.output === 'number')
    // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: prices.json ships with the skill in this shape.
    .map(([key, entry]) => [key, { input: entry.input as number, output: entry.output as number }])
)

export function modelPrice(provider: string, model: string | null | undefined): ModelPrice | null {
  return model ? (PRICES[`${provider}/${model}`] ?? null) : null
}

export const formatUsd = (value: number) =>
  Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2).replace(/0$/, '')}`
