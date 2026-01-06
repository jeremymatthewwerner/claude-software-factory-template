/**
 * Simple calculator module for testing the software factory
 *
 * NOTE: This module intentionally contains bugs for testing purposes.
 * The factory agents should be able to identify and fix these issues.
 */

export interface CalculationResult {
  value: number;
  operation: string;
  inputs: number[];
}

/**
 * Add two or more numbers
 */
export function add(...numbers: number[]): CalculationResult {
  const value = numbers.reduce((sum, n) => sum + n, 0);
  return {
    value,
    operation: 'add',
    inputs: numbers,
  };
}

/**
 * Subtract numbers (first number minus all subsequent numbers)
 */
export function subtract(first: number, ...rest: number[]): CalculationResult {
  const value = rest.reduce((diff, n) => diff - n, first);
  return {
    value,
    operation: 'subtract',
    inputs: [first, ...rest],
  };
}

/**
 * Multiply two or more numbers
 */
export function multiply(...numbers: number[]): CalculationResult {
  const value = numbers.reduce((product, n) => product * n, 1);
  return {
    value,
    operation: 'multiply',
    inputs: numbers,
  };
}

/**
 * Divide first number by subsequent numbers
 *
 * @throws Error if any divisor is zero
 */
export function divide(first: number, ...rest: number[]): CalculationResult {
  if (rest.some((n) => n === 0)) {
    throw new Error('Division by zero');
  }
  const value = rest.reduce((quotient, n) => quotient / n, first);
  return {
    value,
    operation: 'divide',
    inputs: [first, ...rest],
  };
}

/**
 * Calculate modulo (remainder of division)
 *
 * @throws Error if divisor is zero
 */
export function modulo(dividend: number, divisor: number): CalculationResult {
  if (divisor === 0) {
    throw new Error('Division by zero');
  }
  return {
    value: dividend % divisor,
    operation: 'modulo',
    inputs: [dividend, divisor],
  };
}

/**
 * Calculate the average of numbers
 */
export function average(...numbers: number[]): CalculationResult {
  if (numbers.length === 0) {
    return {
      value: 0,
      operation: 'average',
      inputs: [],
    };
  }
  const sum = numbers.reduce((s, n) => s + n, 0);
  return {
    value: sum / numbers.length,
    operation: 'average',
    inputs: numbers,
  };
}

/**
 * Calculate percentage
 * Returns what percent `part` is of `whole`
 */
export function percentage(part: number, whole: number): CalculationResult {
  // TODO: Handle edge case when whole is 0
  return {
    value: (part / whole) * 100,
    operation: 'percentage',
    inputs: [part, whole],
  };
}

/**
 * Calculate power (base^exponent)
 */
export function power(base: number, exponent: number): CalculationResult {
  return {
    value: Math.pow(base, exponent),
    operation: 'power',
    inputs: [base, exponent],
  };
}

/**
 * Calculate square root
 *
 * TODO: Should handle negative numbers gracefully
 */
export function squareRoot(n: number): CalculationResult {
  return {
    value: Math.sqrt(n),
    operation: 'squareRoot',
    inputs: [n],
  };
}
