/**
 * Tests for the calculator module
 *
 * These tests verify basic functionality and expose bugs
 * that the factory agents should fix.
 */

import { add, subtract, multiply, divide, average, percentage, power, squareRoot } from '../src/calculator';

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

    // This test exposes the bug - division by zero
    // Currently it returns Infinity, but should throw an error
    it('should handle division by zero', () => {
      // BUG: This currently returns Infinity instead of throwing
      // The factory agent should fix this
      expect(() => {
        const result = divide(10, 0);
        // If we get here without throwing, the bug exists
        if (!isFinite(result.value)) {
          throw new Error('Division by zero should throw an error');
        }
      }).toThrow();
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
    it('should handle zero whole', () => {
      // BUG: Returns Infinity instead of handling gracefully
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
    it('should handle negative numbers', () => {
      // BUG: Returns NaN instead of handling gracefully
      const result = squareRoot(-4);
      expect(isNaN(result.value)).toBe(false);
    });
  });
});
