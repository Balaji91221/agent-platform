import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 16, children, ...rest }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...rest}>
      {children}
    </svg>
  );
}

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.9,
} as const;

export function ClockMark(p: IconProps) {
  return (
    <Icon {...p} {...stroke} strokeWidth={2.4} strokeLinecap="round">
      <path d="M12 6.5V12l3.5 2" />
      <circle cx="12" cy="12" r="8.5" />
    </Icon>
  );
}

export function DashboardIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke}>
      <rect x="3" y="3" width="7" height="9" rx="2" />
      <rect x="14" y="3" width="7" height="5" rx="2" />
      <rect x="14" y="12" width="7" height="9" rx="2" />
      <rect x="3" y="16" width="7" height="5" rx="2" />
    </Icon>
  );
}

export function ChatIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke} strokeLinejoin="round">
      <path d="M20 15a2 2 0 0 1-2 2H8l-4 3V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z" />
      <path d="M9 9h6M9 12.5h4" />
    </Icon>
  );
}

export function AgentIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke}>
      <rect x="4" y="7" width="16" height="12" rx="3" />
      <path d="M12 3v4M9 13h.01M15 13h.01" />
    </Icon>
  );
}

export function TeamIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke}>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 19c0-3 2.7-4.6 6-4.6s6 1.6 6 4.6" />
      <circle cx="17.5" cy="9" r="2.4" />
      <path d="M16 14.2c3 .2 5 1.8 5 4.8" />
    </Icon>
  );
}

export function RunsIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke} strokeLinecap="round">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </Icon>
  );
}

export function LinkIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke}>
      <path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
    </Icon>
  );
}

export function BellIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke}>
      <path d="M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6" />
      <path d="M10.5 20a2 2 0 0 0 3 0" />
    </Icon>
  );
}

export function ArchitectureIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke}>
      <rect x="9" y="3" width="6" height="5" rx="1.5" />
      <rect x="3" y="16" width="6" height="5" rx="1.5" />
      <rect x="15" y="16" width="6" height="5" rx="1.5" />
      <path d="M12 8v4M6 16v-2h12v2" />
    </Icon>
  );
}

export function SearchIcon(p: IconProps) {
  return (
    <Icon {...p} {...stroke} strokeWidth={2}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </Icon>
  );
}

export function PlusIcon({ size = 15, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2.4} strokeLinecap="round">
      <path d="M12 5v14M5 12h14" />
    </Icon>
  );
}

export function CheckIcon({ size = 14, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </Icon>
  );
}

export function CheckCircleIcon({ size = 14, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </Icon>
  );
}

export function ClockCircleIcon({ size = 14, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Icon>
  );
}

export function AlertCircleIcon({ size = 14, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5M12 16h.01" />
    </Icon>
  );
}

export function TokenIcon({ size = 14, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v9m0 0 3-3m-3 3-3-3" />
      <rect x="4" y="14" width="16" height="6" rx="2" />
    </Icon>
  );
}

export function TrendUpIcon({ size = 11, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 15l6-6 6 6" />
    </Icon>
  );
}

export function TrendDownIcon({ size = 11, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9l6 6 6-6" />
    </Icon>
  );
}

export function RefreshIcon({ size = 14, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 11A8 8 0 1 0 12 20" />
      <path d="M20 5v6h-6" />
    </Icon>
  );
}

export function MoreIcon({ size = 15, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} fill="currentColor">
      <circle cx="5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="19" cy="12" r="1.7" />
    </Icon>
  );
}

export function PlayIcon({ size = 13, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} fill="currentColor">
      <path d="M7 4v16l13-8z" />
    </Icon>
  );
}

export function InfoIcon({ size = 15, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-5M12 8h.01" />
    </Icon>
  );
}

export function SendIcon({ size = 17, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 19V5M6 11l6-6 6 6" />
    </Icon>
  );
}

export function ArrowRightIcon({ size = 14, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2} strokeLinecap="round">
      <path d="M4 12h14M13 7l5 5-5 5" />
    </Icon>
  );
}

export function BlockedIcon({ size = 14, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={2} strokeLinecap="round">
      <path d="M12 8v5M12 16.5v.01" />
      <circle cx="12" cy="12" r="9" />
    </Icon>
  );
}

export function SparkleIcon({ size = 15, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} fill="currentColor">
      <path d="M12 2l1.9 5.6L19.5 9l-4.4 3.3L16.4 18 12 14.9 7.6 18l1.3-5.7L4.5 9l5.6-1.4z" />
    </Icon>
  );
}

export function BigSparkleIcon({ size = 26, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} fill="currentColor">
      <path d="M12 1.8l1.7 6 5.9-2.4-3.6 5.2 5.2 3.6-6.2.4 1.6 6-4.6-4.2-4.6 4.2 1.6-6-6.2-.4 5.2-3.6L4.4 5.4l5.9 2.4z" />
    </Icon>
  );
}

/* ---- app / brand marks used inside .sq tiles ---- */

export function MailIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="m3 7.5 9 6 9-6" />
    </Icon>
  );
}

export function MailSendIcon({ size = 15, strokeWidth = 1.9, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <path d="m3 5 9 6 9-6" />
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
    </Icon>
  );
}

export function SlackIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <rect x="4" y="4" width="16" height="16" rx="4.5" />
      <path d="M9 9.5h6M9 13.5h4" />
    </Icon>
  );
}

export function SheetsIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <rect x="4" y="3" width="16" height="18" rx="2.5" />
      <path d="M8 9h8M8 13h8M8 17h4" />
    </Icon>
  );
}

export function ZendeskIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <path d="M4 4h16v10a6 6 0 0 1-6 6H4z" />
    </Icon>
  );
}

export function NotionIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <rect x="4" y="3" width="16" height="18" rx="2.5" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </Icon>
  );
}

export function LinearIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <rect x="4" y="4" width="16" height="16" rx="5" />
      <path d="M8 12h8" />
    </Icon>
  );
}

export function StripeIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <path d="M6 8.5c0-1.4 1.5-2.5 4-2.5s4 .6 4 .6M6 15c1 .7 2.5 1.2 4.5 1.2 2.6 0 4-1 4-2.5 0-3-8-2.2-8-5" />
    </Icon>
  );
}

export function GlobeIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c4 4.5 4 12.5 0 17M12 3.5c-4 4.5-4 12.5 0 17" />
    </Icon>
  );
}

export function DocsIcon({ size = 15, strokeWidth = 2, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeWidth={strokeWidth}>
      <rect x="4" y="4" width="16" height="16" rx="4" />
      <path d="M9 10h6M9 14h4" />
    </Icon>
  );
}

export function StandupIcon({ size = 16, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke}>
      <rect x="3" y="4" width="18" height="14" rx="2.5" />
      <path d="M8 9.5h8M8 13h5m-5 5-2 3" />
    </Icon>
  );
}

export function TriageIcon({ size = 16, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke}>
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
      <circle cx="12" cy="12" r="4.5" />
    </Icon>
  );
}

export function InvoiceIcon({ size = 16, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke}>
      <path d="M6 3h12v18l-6-3-6 3z" />
      <path d="M9 8h6M9 12h6" />
    </Icon>
  );
}

export function MetricsIcon({ size = 16, ...p }: IconProps) {
  return (
    <Icon size={size} {...p} {...stroke} strokeLinecap="round">
      <path d="M4 18V9M10 18V5M16 18v-7M3 21h18" />
    </Icon>
  );
}
