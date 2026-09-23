import { describe, expect, it } from 'vitest'
import { applyMarkingScanKey, quickMarkingCodeCheck } from './scanMarking'

describe('applyMarkingScanKey', () => {
  it('submits on Enter with current buffer', () => {
    const result = applyMarkingScanKey('0104600000000010215', { key: 'Enter', ctrlKey: false, altKey: false, metaKey: false })
    expect(result).toEqual({
      next: '0104600000000010215',
      handled: true,
      submit: true,
    })
  })

  it('submits on Tab with current buffer', () => {
    const result = applyMarkingScanKey('0104600000000010215', { key: 'Tab', ctrlKey: false, altKey: false, metaKey: false })
    expect(result.submit).toBe(true)
  })

  it('appends printable characters', () => {
    const result = applyMarkingScanKey('01', { key: '3', ctrlKey: false, altKey: false, metaKey: false })
    expect(result).toEqual({ next: '013', handled: true })
  })
})

describe('quickMarkingCodeCheck', () => {
  it('accepts long latin codes', () => {
    expect(quickMarkingCodeCheck('0104600000000010215ABC1234567890')).toBeNull()
  })

  it('rejects empty codes', () => {
    expect(quickMarkingCodeCheck('')).toMatch(/пустой/i)
  })
})
