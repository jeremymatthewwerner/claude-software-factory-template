import type { ReactElement } from 'react';
import RootLayout, { metadata } from '@/app/layout';

describe('app/layout.tsx', () => {
  describe('metadata export', () => {
    it('has the exact title "Software Factory" (renders in the browser tab)', () => {
      expect(metadata.title).toBe('Software Factory');
    });

    it('has the exact description used by SEO/social embeds', () => {
      expect(metadata.description).toBe('Autonomous software development powered by Claude');
    });
  });

  describe('RootLayout component', () => {
    const renderElement = (children: React.ReactNode): ReactElement => {
      const result = RootLayout({ children });
      if (!result || typeof result !== 'object' || !('type' in result)) {
        throw new Error('RootLayout did not return a React element');
      }
      return result as ReactElement;
    };

    it('returns an <html> root element', () => {
      const element = renderElement('child-content');
      expect(element.type).toBe('html');
    });

    it('sets lang="en" on the <html> element (a11y requirement)', () => {
      const element = renderElement('child-content');
      expect((element.props as { lang?: string }).lang).toBe('en');
    });

    it('wraps children inside a <body> element (correct document structure)', () => {
      const element = renderElement('child-content');
      const body = (element.props as { children: ReactElement }).children;
      expect(body.type).toBe('body');
    });

    it('passes children through into <body> unchanged (referential identity)', () => {
      const children = { sentinel: true } as unknown as React.ReactNode;
      const element = renderElement(children);
      const body = (element.props as { children: ReactElement }).children;
      expect((body.props as { children: React.ReactNode }).children).toBe(children);
    });

    it('renders <body> as the only direct child of <html> (no sibling nodes)', () => {
      const element = renderElement('child-content');
      const htmlChildren = (element.props as { children: ReactElement | ReactElement[] }).children;
      expect(Array.isArray(htmlChildren)).toBe(false);
    });

    it('is exported as the default export and is callable', () => {
      expect(typeof RootLayout).toBe('function');
    });
  });
});
