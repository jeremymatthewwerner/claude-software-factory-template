# Frontend

A Next.js frontend for your Claude Software Factory project.

## Quick Start

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Open in browser
open http://localhost:3000
```

## Scripts

| Script | Description |
|--------|-------------|
| `npm run dev` | Start development server |
| `npm run build` | Build for production |
| `npm start` | Start production server |
| `npm run lint` | Run ESLint |
| `npm run format` | Format with Prettier |
| `npm run format:check` | Check formatting |
| `npm run typecheck` | TypeScript type check |
| `npm test` | Run Jest tests |
| `npm run test:coverage` | Run tests with coverage |

## Project Structure

```
frontend/
├── src/
│   ├── app/                 # Next.js App Router
│   │   ├── layout.tsx       # Root layout
│   │   ├── page.tsx         # Home page
│   │   ├── page.module.css  # Page styles
│   │   └── globals.css      # Global styles
│   └── components/          # Shared components
├── __tests__/               # Test files
├── public/                  # Static assets
├── package.json
├── tsconfig.json
├── next.config.js
└── README.md
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API URL | `http://localhost:8000` |

Create a `.env.local` file for local development:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Features

- **TypeScript** - Full type safety
- **App Router** - Next.js 14 App Router
- **Dark Mode** - Automatic dark/light mode based on system preference
- **API Integration** - Connects to FastAPI backend
- **Testing** - Jest + React Testing Library

## Extending

### Adding a New Page

Create a new file in `src/app/`:

```tsx
// src/app/about/page.tsx
export default function AboutPage() {
  return <h1>About</h1>;
}
```

### Adding a Component

```tsx
// src/components/Button.tsx
interface ButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
}

export function Button({ children, onClick }: ButtonProps) {
  return <button onClick={onClick}>{children}</button>;
}
```

### API Calls

```tsx
const apiUrl = process.env.NEXT_PUBLIC_API_URL;

async function fetchData() {
  const res = await fetch(`${apiUrl}/api/endpoint`);
  return res.json();
}
```

## Deployment

This app is configured to deploy on Railway or Vercel. See the root README for deployment instructions.
