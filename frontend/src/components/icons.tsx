import type { JSX, SVGProps } from "react";

/**
 * Set de iconos propio (stroke 1.6, currentColor) para no depender de emoji/glifos unicode
 * como afordancias — nav, adjuntar, volver, imagen. Un solo archivo, sin librería.
 */

function base(props: SVGProps<SVGSVGElement>): SVGProps<SVGSVGElement> {
  return {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
    ...props,
  };
}

export function ArrowLeftIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <svg {...base(props)}>
      <path d="M19 12H5M11 6l-6 6 6 6" />
    </svg>
  );
}

export function PaperclipIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <svg {...base(props)}>
      <path d="M20 12.5 12.5 20a4.5 4.5 0 0 1-6.36-6.36l8-8a3 3 0 0 1 4.24 4.24l-7.6 7.6a1.5 1.5 0 0 1-2.12-2.12l6.9-6.9" />
    </svg>
  );
}

export function ChevronRightIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <svg {...base(props)}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

export function LayersIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <svg {...base(props)}>
      <path d="M12 3 20 8 12 13 4 8Z" />
      <path d="M4 13 12 18 20 13" />
    </svg>
  );
}

export function ImageIcon(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="1.5" fill="currentColor" stroke="none" />
      <path d="m4 17 5-5 4 4 3-3 4 4" />
    </svg>
  );
}
