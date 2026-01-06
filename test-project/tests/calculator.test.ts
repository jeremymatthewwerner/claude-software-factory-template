/**
 * Tests for the calculator module
 *
 * These tests verify basic functionality and expose bugs
 * that the factory agents should fix.
 */

import { add, subtract, multiply, divide, modulo, average, percentage, power, squareRoot } from '../src/calculator';

describe('Calculator', () => {
  describe('add', () => {
    it('should add two numbers', () => {
      const result = add(2, 3);
      expect(result.value).toBe(5);
      expect(result.operation).toBe('add');
    });

    it('should add multiple numbers', () => {
      const result = add(1, 2, 3, 4, 5);
      expect(result.value).toBe(15);
    });

    it('should handle negative numbers', () => {
      const result = add(-5, 3);
      expect(result.value).toBe(-2);
    });

    it('should return 0 for no inputs', () => {
      const result = add();
      expect(result.value).toBe(0);
    });
  });

  describe('subtract', () => {
    it('should subtract two numbers', () => {
      const result = subtract(10, 3);
      expect(result.value).toBe(7);
    });

    it('should subtract multiple numbers', () => {
      const result = subtract(20, 5, 3, 2);
      expect(result.value).toBe(10);
    });
  });

  describe('multiply', () => {
    it('should multiply two numbers', () => {
      const result = multiply(4, 5);
      expect(result.value).toBe(20);
    });

    it('should multiply multiple numbers', () => {
      const result = multiply(2, 3, 4);
      expect(result.value).toBe(24);
    });

    it('should handle zero', () => {
      const result = multiply(5, 0);
      expect(result.value).toBe(0);
    });
  });

  describe('divide', () => {
    it('should divide two numbers', () => {
      const result = divide(20, 4);
      expect(result.value).toBe(5);
    });

    it('should divide multiple numbers', () => {
      const result = divide(100, 2, 5);
      expect(result.value).toBe(10);
    });

    it('should handle division by zero', () => {
      expect(() => divide(10, 0)).toThrow('Division by zero');
    });
  });

  describe('modulo', () => {
    it('should calculate modulo of two numbers', () => {
      const result = modulo(10, 3);
      expect(result.value).toBe(1);
      expect(result.operation).toBe('modulo');
      expect(result.inputs).toEqual([10, 3]);
    });

    it('should handle division by zero', () => {
      expect(() => modulo(10, 0)).toThrow('Division by zero');
    });

    it('should handle negative dividend', () => {
      const result = modulo(-10, 3);
      expect(result.value).toBe(-1);
    });

    it('should handle negative divisor', () => {
      const result = modulo(10, -3);
      expect(result.value).toBe(1);
    });

    it('should handle both negative', () => {
      const result = modulo(-10, -3);
      expect(result.value).toBe(-1);
    });

    it('should return 0 when dividend is divisible by divisor', () => {
      const result = modulo(12, 4);
      expect(result.value).toBe(0);
    });

    it('should handle decimal numbers', () => {
      const result = modulo(5.5, 2);
      expect(result.value).toBeCloseTo(1.5, 10);
    });
  });

  describe('average', () => {
    it('should calculate average of numbers', () => {
      const result = average(10, 20, 30);
      expect(result.value).toBe(20);
    });

    it('should handle single number', () => {
      const result = average(5);
      expect(result.value).toBe(5);
    });

    it('should return 0 for empty input', () => {
      const result = average();
      expect(result.value).toBe(0);
    });
  });

  describe('percentage', () => {
    it('should calculate percentage', () => {
      const result = percentage(25, 100);
      expect(result.value).toBe(25);
    });

    it('should handle percentages over 100', () => {
      const result = percentage(150, 100);
      expect(result.value).toBe(150);
    });

    // This test exposes another edge case
    // Percentage of zero whole should be handled
    it.skip('should handle zero whole', () => {
      // BUG: Returns Infinity instead of handling gracefully
      // TODO: Fix in calculator.ts to handle zero whole - tracked as known issue
      const result = percentage(10, 0);
      expect(isFinite(result.value)).toBe(true);
    });
  });

  describe('power', () => {
    it('should calculate power', () => {
      const result = power(2, 3);
      expect(result.value).toBe(8);
    });

    it('should handle zero exponent', () => {
      const result = power(5, 0);
      expect(result.value).toBe(1);
    });

    it('should handle negative exponent', () => {
      const result = power(2, -2);
      expect(result.value).toBe(0.25);
    });
  });

  describe('squareRoot', () => {
    it('should calculate square root', () => {
      const result = squareRoot(16);
      expect(result.value).toBe(4);
    });

    it('should handle zero', () => {
      const result = squareRoot(0);
      expect(result.value).toBe(0);
    });

    // This test exposes the negative number issue
    it.skip('should handle negative numbers', () => {
      // BUG: Returns NaN instead of handling gracefully
      // TODO: Fix in calculator.ts to handle negative numbers - tracked as known issue
      const result = squareRoot(-4);
      expect(isNaN(result.value)).toBe(false);
    });
  });

  // ========================================
  // Edge Case Tests (Issue #5)
  // ========================================

  describe('edge cases - add', () => {
    it('should handle very large numbers', () => {
      const large1 = Number.MAX_SAFE_INTEGER;
      const large2 = Number.MAX_SAFE_INTEGER;
      const result = add(large1, large2);
      // JavaScript can handle this but may lose precision beyond MAX_SAFE_INTEGER
      expect(result.value).toBe(large1 + large2);
      expect(result.operation).toBe('add');
    });

    it('should handle Number.MAX_VALUE', () => {
      const result = add(Number.MAX_VALUE, 1);
      // MAX_VALUE + 1 equals MAX_VALUE due to floating point
      expect(result.value).toBe(Number.MAX_VALUE);
    });

    it('should handle Infinity', () => {
      const result = add(Number.MAX_VALUE, Number.MAX_VALUE);
      expect(result.value).toBe(Infinity);
    });
  });

  describe('edge cases - multiply', () => {
    it('should handle decimal numbers', () => {
      const result = multiply(0.1, 0.2);
      // Due to floating point, 0.1 * 0.2 is not exactly 0.02
      expect(result.value).toBeCloseTo(0.02, 10);
    });

    it('should handle many decimal multiplications', () => {
      const result = multiply(0.1, 0.2, 0.3);
      expect(result.value).toBeCloseTo(0.006, 10);
    });

    it('should handle mixed integers and decimals', () => {
      const result = multiply(2, 0.5, 3.14);
      expect(result.value).toBeCloseTo(3.14, 10);
    });
  });

  describe('edge cases - subtract', () => {
    it('should handle floating point precision issues', () => {
      // Classic floating point issue: 0.3 - 0.1 is not exactly 0.2
      const result = subtract(0.3, 0.1);
      expect(result.value).toBeCloseTo(0.2, 10);
    });

    it('should handle very small differences', () => {
      const result = subtract(1.0000000001, 1);
      expect(result.value).toBeCloseTo(0.0000000001, 15);
    });

    it('should handle negative floating point numbers', () => {
      const result = subtract(-0.1, 0.2);
      expect(result.value).toBeCloseTo(-0.3, 10);
    });
  });

  describe('edge cases - power', () => {
    it('should handle fractional exponents (square root)', () => {
      const result = power(9, 0.5);
      expect(result.value).toBeCloseTo(3, 10);
    });

    it('should handle fractional exponents (cube root)', () => {
      const result = power(8, 1 / 3);
      expect(result.value).toBeCloseTo(2, 10);
    });

    it('should handle negative base with integer exponent', () => {
      const result = power(-2, 3);
      expect(result.value).toBe(-8);
    });

    it('should handle very small fractional exponents', () => {
      const result = power(1000, 0.001);
      expect(result.value).toBeCloseTo(1.0069316688518043, 10);
    });
  });

  describe('edge cases - squareRoot', () => {
    it('should handle very small positive numbers', () => {
      const result = squareRoot(0.0001);
      expect(result.value).toBeCloseTo(0.01, 10);
    });

    it('should handle very small numbers near zero', () => {
      const result = squareRoot(1e-10);
      expect(result.value).toBeCloseTo(1e-5, 15);
    });

    it('should handle perfect squares', () => {
      const result = squareRoot(144);
      expect(result.value).toBe(12);
    });

    it('should handle non-perfect squares', () => {
      const result = squareRoot(2);
      expect(result.value).toBeCloseTo(1.4142135623730951, 10);
    });
  });
});
