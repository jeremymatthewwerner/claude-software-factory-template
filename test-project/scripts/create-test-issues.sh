#!/bin/bash
#
# Create test issues to validate the software factory
#
# Usage:
#   ./scripts/create-test-issues.sh [--all | --bug | --enhancement | --qa]
#
set -e

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}Creating test issues for factory validation...${NC}"
echo ""

# Bug issue - Division by zero
create_bug_issue() {
    echo "Creating bug issue: Division by zero..."

    gh issue create \
        --title "Bug: divide() function doesn't handle division by zero" \
        --body "## Description
The \`divide()\` function in \`test-project/src/calculator.ts\` returns \`Infinity\` when dividing by zero instead of throwing an appropriate error.

## Steps to Reproduce
1. Call \`divide(10, 0)\`
2. Observe that it returns \`{ value: Infinity, ... }\`

## Expected Behavior
The function should throw an error like \`Error: Division by zero\` when any divisor is zero.

## Actual Behavior
Returns \`Infinity\` which can cause downstream issues.

## Test Case
There's a failing test in \`tests/calculator.test.ts\` that validates this:
\`\`\`typescript
it('should handle division by zero', () => {
  expect(() => divide(10, 0)).toThrow();
});
\`\`\`

## Acceptance Criteria
- [ ] \`divide()\` throws an error when any divisor is 0
- [ ] Error message is descriptive
- [ ] All tests pass
" \
        --label "bug" \
        --label "ai-ready" \
        --label "priority-medium"

    echo -e "${GREEN}✓ Bug issue created${NC}"
}

# Enhancement issue - Add modulo operation
create_enhancement_issue() {
    echo "Creating enhancement issue: Add modulo operation..."

    gh issue create \
        --title "Enhancement: Add modulo (remainder) operation to calculator" \
        --body "## Description
Add a \`modulo()\` function to the calculator that returns the remainder of division.

## Requirements
- Function signature: \`modulo(dividend: number, divisor: number): CalculationResult\`
- Should handle negative numbers correctly
- Should throw error for division by zero (like \`divide()\` should)

## Example
\`\`\`typescript
modulo(10, 3) // => { value: 1, operation: 'modulo', inputs: [10, 3] }
modulo(10, 0) // => throws Error('Division by zero')
\`\`\`

## Acceptance Criteria
- [ ] \`modulo()\` function added to \`src/calculator.ts\`
- [ ] Function exported properly
- [ ] Tests added to \`tests/calculator.test.ts\`
- [ ] All tests pass
" \
        --label "enhancement" \
        --label "ai-ready" \
        --label "priority-low"

    echo -e "${GREEN}✓ Enhancement issue created${NC}"
}

# QA issue - Improve test coverage
create_qa_issue() {
    echo "Creating QA issue: Improve test coverage..."

    gh issue create \
        --title "QA: Improve test coverage for edge cases" \
        --body "## Description
The calculator tests need better coverage of edge cases.

## Missing Test Cases
1. \`add()\` with very large numbers
2. \`multiply()\` with decimal numbers
3. \`subtract()\` with floating point precision issues
4. \`power()\` with fractional exponents
5. \`squareRoot()\` with very small numbers

## Current Coverage
Run \`npm run test:coverage\` to see current coverage report.

## Acceptance Criteria
- [ ] Add tests for the cases listed above
- [ ] Coverage should be at least 80%
- [ ] All tests should pass
" \
        --label "enhancement" \
        --label "ai-ready" \
        --label "priority-low"

    echo -e "${GREEN}✓ QA issue created${NC}"
}

# Process arguments
case "${1:-all}" in
    --bug)
        create_bug_issue
        ;;
    --enhancement)
        create_enhancement_issue
        ;;
    --qa)
        create_qa_issue
        ;;
    --all|*)
        create_bug_issue
        echo ""
        create_enhancement_issue
        echo ""
        create_qa_issue
        ;;
esac

echo ""
echo -e "${GREEN}Done! Check your repository issues.${NC}"
echo "The 'ai-ready' labeled issues should trigger the Code Agent."
