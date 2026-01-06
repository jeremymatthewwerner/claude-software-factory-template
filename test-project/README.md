# Factory Test Project

This is a minimal test project used to validate that the Claude Software Factory is working correctly.

## Purpose

This project provides:
1. **Real code** - Simple TypeScript functions with tests
2. **Intentional issues** - Bugs and TODOs that agents can fix
3. **Test scenarios** - Scripts to create issues and trigger workflows
4. **Validation** - Verify the factory handles real work

## Structure

```
test-project/
├── src/
│   └── calculator.ts    # Simple calculator with a bug
├── tests/
│   └── calculator.test.ts
├── scripts/
│   └── create-test-issues.sh  # Create issues for agents
├── package.json
└── README.md
```

## The Intentional Bug

`src/calculator.ts` has an intentional bug in the `divide` function - it doesn't handle division by zero properly. This allows you to:

1. Create an issue describing the bug
2. Add the `ai-ready` and `bug` labels
3. Watch the Code Agent fix it
4. Validate the fix through tests

## Running Tests

```bash
cd test-project
npm install
npm test
```

## Creating Test Issues

```bash
./scripts/create-test-issues.sh
```

This will create sample issues that trigger different agents.

## Factory Validation Checklist

After setting up your factory, use this project to verify:

- [ ] `factory status` shows this repo
- [ ] Creating an `ai-ready` issue triggers the Code Agent
- [ ] The Code Agent can read and modify code
- [ ] Tests run in CI
- [ ] PR gets created with the fix
- [ ] Issue gets closed when PR merges
